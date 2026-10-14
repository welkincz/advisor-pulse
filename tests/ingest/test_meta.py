from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from pulse.contracts import duckdb_columns
from pulse.contracts.enums import CheckSeverity, CheckStatus, LoadStatus, RunType, StageStatus
from pulse.contracts.meta import CheckResult, LoadManifest, RejectedRow, RunLogRow, Watermark
from pulse.ingest import meta
from pulse.warehouse import TABLES, connect, init_warehouse, transaction, warehouse_path

T0 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64


@pytest.fixture
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    c = connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def _wm(value: datetime = T0, run_id: str = "run-1") -> Watermark:
    return Watermark(
        source="snowflake",
        table_name="activity",
        watermark_column="_EXTRACTED_AT",
        watermark_value=value,
        updated_at=value,
        run_id=run_id,
    )


def _manifest(
    path: str = "a.parquet", sha: str = SHA_A, status: LoadStatus = LoadStatus.LOADED
) -> LoadManifest:
    return LoadManifest(
        file_path=path,
        file_sha256=sha,
        source="snowflake",
        table_name="activity",
        batch_id=f"run-1:{sha[:8]}",
        row_count=10,
        rows_loaded=9 if status is LoadStatus.LOADED else 0,
        rows_quarantined=1 if status is LoadStatus.LOADED else 0,
        status=status,
        loaded_at=T0,
        run_id="run-1",
    )


# ── init and DDL ─────────────────────────────────────────────────────────────


def test_init_is_idempotent(con: duckdb.DuckDBPyConnection) -> None:
    meta.set_watermark(con, _wm())
    init_warehouse(con)
    init_warehouse(con)
    assert meta.get_watermark(con, "snowflake", "activity") == _wm()
    schemas = {
        r[0] for r in con.execute("SELECT schema_name FROM information_schema.schemata").fetchall()
    }
    assert {"raw", "meta", "quarantine"} <= schemas


@pytest.mark.parametrize("spec", TABLES, ids=lambda s: s.name)
def test_ddl_matches_contract(con: duckdb.DuckDBPyConnection, spec: object) -> None:
    from pulse.warehouse import TableSpec, qualified

    assert isinstance(spec, TableSpec)
    described = [
        (name, sql_type, nullable == "YES")
        for name, sql_type, nullable, *_ in con.execute(
            f"DESCRIBE {qualified(spec.name)}"
        ).fetchall()
    ]
    expected = duckdb_columns(spec.model)
    # PK columns are NOT NULL by definition, and non-nullable in their contracts too.
    assert described == expected


@pytest.mark.parametrize("spec", [s for s in TABLES if s.primary_key], ids=lambda s: s.name)
def test_primary_keys_exist(con: duckdb.DuckDBPyConnection, spec: object) -> None:
    from pulse.warehouse import TableSpec

    assert isinstance(spec, TableSpec)
    schema, table = spec.name.split(".")
    rows = con.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE schema_name = ? AND table_name = ? AND constraint_type = 'PRIMARY KEY'",
        [schema, table],
    ).fetchall()
    assert [tuple(r[0]) for r in rows] == [spec.primary_key]


def test_connect_uses_data_dir_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path / "nested" / "data"))
    assert warehouse_path() == tmp_path / "nested" / "data" / "warehouse.duckdb"
    c = connect()
    init_warehouse(c)
    meta.set_watermark(c, _wm())
    c.close()
    assert warehouse_path().exists()
    c2 = connect(read_only=True)
    assert meta.get_watermark_value(c2, "snowflake", "activity") == T0
    c2.close()


# ── watermarks ───────────────────────────────────────────────────────────────


def test_watermark_round_trip_and_upsert(con: duckdb.DuckDBPyConnection) -> None:
    assert meta.get_watermark(con, "snowflake", "activity") is None
    meta.set_watermark(con, _wm())
    later = T0 + timedelta(days=7)
    meta.set_watermark(con, _wm(later, "run-2"))
    got = meta.get_watermark(con, "snowflake", "activity")
    assert got is not None and got.watermark_value == later and got.run_id == "run-2"
    assert got.watermark_value.tzinfo is not None
    assert con.execute("SELECT count(*) FROM meta.watermark").fetchone() == (1,)


def test_watermark_never_moves_backwards(con: duckdb.DuckDBPyConnection) -> None:
    meta.set_watermark(con, _wm(T0 + timedelta(days=7)))
    with pytest.raises(meta.WatermarkRegressionError):
        meta.set_watermark(con, _wm(T0))
    meta.set_watermark(con, _wm(T0), allow_regression=True)
    assert meta.get_watermark_value(con, "snowflake", "activity") == T0


# ── transactions ─────────────────────────────────────────────────────────────


def test_failed_transaction_leaves_watermark_and_manifest_unchanged(
    con: duckdb.DuckDBPyConnection,
) -> None:
    meta.set_watermark(con, _wm())
    meta.record_manifest(con, _manifest("old.parquet"))

    with pytest.raises(RuntimeError, match="boom"), transaction(con):
        meta.record_manifest(con, _manifest("new.parquet", SHA_B))
        meta.set_watermark(con, _wm(T0 + timedelta(days=7), "run-2"))
        meta.write_run_log(con, _run_log())
        raise RuntimeError("boom")

    assert meta.get_watermark_value(con, "snowflake", "activity") == T0
    assert [m.file_path for m in meta.get_manifest(con)] == ["old.parquet"]
    assert meta.get_run_log(con) == []


def test_successful_transaction_commits_together(con: duckdb.DuckDBPyConnection) -> None:
    with transaction(con):
        meta.record_manifest(con, _manifest())
        meta.set_watermark(con, _wm())
    assert meta.is_file_loaded(con, "a.parquet", SHA_A)
    assert meta.get_watermark_value(con, "snowflake", "activity") == T0


def test_transaction_rolls_back_on_watermark_regression(con: duckdb.DuckDBPyConnection) -> None:
    meta.set_watermark(con, _wm(T0 + timedelta(days=7)))
    with pytest.raises(meta.WatermarkRegressionError), transaction(con):
        meta.record_manifest(con, _manifest())
        meta.set_watermark(con, _wm(T0))
    assert meta.get_manifest(con) == []


# ── manifest ─────────────────────────────────────────────────────────────────


def test_is_file_loaded_distinguishes_hash(con: duckdb.DuckDBPyConnection) -> None:
    meta.record_manifest(con, _manifest("a.parquet", SHA_A))
    assert meta.is_file_loaded(con, "a.parquet", SHA_A)
    assert not meta.is_file_loaded(con, "a.parquet", SHA_B)
    assert not meta.is_file_loaded(con, "b.parquet", SHA_A)


def test_failed_file_is_not_loaded_until_it_succeeds(con: duckdb.DuckDBPyConnection) -> None:
    meta.record_manifest(con, _manifest(status=LoadStatus.FAILED))
    assert not meta.is_file_loaded(con, "a.parquet", SHA_A)
    meta.record_manifest(con, _manifest(status=LoadStatus.LOADED))
    assert meta.is_file_loaded(con, "a.parquet", SHA_A)
    assert len(meta.get_manifest(con, "a.parquet")) == 1


def test_changed_file_is_a_second_manifest_row(con: duckdb.DuckDBPyConnection) -> None:
    meta.record_manifest(con, _manifest("a.parquet", SHA_A))
    meta.record_manifest(con, _manifest("a.parquet", SHA_B))
    assert {m.file_sha256 for m in meta.get_manifest(con, "a.parquet")} == {SHA_A, SHA_B}


# ── run log, checks, quarantine ──────────────────────────────────────────────


def _run_log(status: StageStatus = StageStatus.RUNNING, attempt: int = 1) -> RunLogRow:
    return RunLogRow(
        run_id="run-1",
        run_type=RunType.WEEKLY,
        iso_week_id="2026-W41",
        stage="ingest",
        attempt=attempt,
        status=status,
        started_at=T0,
        ended_at=None if status is StageStatus.RUNNING else T0 + timedelta(seconds=3),
        duration_ms=None if status is StageStatus.RUNNING else 3000,
    )


def test_run_log_attempts_and_status_updates(con: duckdb.DuckDBPyConnection) -> None:
    meta.write_run_log(con, _run_log())
    meta.write_run_log(con, _run_log(StageStatus.FAILED))
    meta.write_run_log(con, _run_log(StageStatus.SUCCESS, attempt=2))
    rows = meta.get_run_log(con, "run-1")
    assert [(r.attempt, r.status) for r in rows] == [
        (1, StageStatus.FAILED),
        (2, StageStatus.SUCCESS),
    ]
    assert meta.get_run_log(con, "other") == []


def test_check_results(con: duckdb.DuckDBPyConnection) -> None:
    row = CheckResult(
        run_id="run-1",
        check_id="DQ031",
        severity=CheckSeverity.WARN,
        status=CheckStatus.WARN,
        observed=3.4,
    )
    meta.write_check_result(con, row)
    meta.write_check_result(con, row.model_copy(update={"status": CheckStatus.PASS}))
    assert [r.status for r in meta.get_check_results(con, "run-1")] == [CheckStatus.PASS]


def _rejected(n: int, batch: str = "b1") -> RejectedRow:
    return RejectedRow(
        rejected_id=f"{batch}:{n}",
        run_id="run-1",
        batch_id=batch,
        source="snowflake",
        table_name="activity",
        source_file="a.parquet",
        source_row=n,
        rule_id="DQ001",
        reason="ACTIVITY_ID is null",
        payload='{"ACTIVITY_ID": null}',
        detected_at=T0,
    )


def test_rejected_rows_bulk_and_rerun_safe(con: duckdb.DuckDBPyConnection) -> None:
    rows = [_rejected(n) for n in range(5)]
    meta.write_rejected_rows(con, rows)
    meta.write_rejected_rows(con, rows)
    meta.write_rejected_rows(con, [])
    meta.write_rejected_rows(con, [_rejected(0, "b2")])
    assert len(meta.get_rejected_rows(con)) == 6
    assert meta.get_rejected_rows(con, "b1") == rows
