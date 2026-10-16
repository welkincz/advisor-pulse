"""Vectorized ingest rules reconciled with the committed defect manifest."""

from __future__ import annotations

import csv
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pulse.contracts.defects import DefectManifest
from pulse.contracts.enums import CheckStatus
from pulse.contracts.sources import SnowflakeActivity, TeradataClient
from pulse.ingest import meta
from pulse.ingest.validate import SchemaDriftError, validate_rows
from pulse.warehouse import connect, init_warehouse

SOURCES = Path(__file__).resolve().parents[2] / "fixtures/sources"
DEFECTS = SOURCES.parent / "defects.json"
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


@pytest.fixture
def warehouse() -> Iterator[duckdb.DuckDBPyConnection]:
    con = connect(":memory:")
    init_warehouse(con)
    yield con
    con.close()


def _validate(
    table: pa.Table,
    *,
    source: str,
    table_name: str,
    source_file: str,
    model: type[SnowflakeActivity] | type[TeradataClient],
    warehouse: duckdb.DuckDBPyConnection | None = None,
    allow_text_coercion: bool = False,
):
    return validate_rows(
        table,
        model,
        source=source,
        table_name=table_name,
        source_file=source_file,
        batch_id="fixture-batch",
        run_id="run-1",
        detected_at=NOW,
        warehouse=warehouse,
        allow_text_coercion=allow_text_coercion,
    )


def test_fixture_rejections_match_exact_defect_manifest(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    expected = DefectManifest.model_validate_json(DEFECTS.read_text())
    wanted = {
        (d.file, d.row, d.rule_id)
        for d in expected.defects
        if d.rule_id in {"DQ001", "DQ002", "DQ003", "DQ004", "DQ005"}
    }
    found: set[tuple[str, int, str]] = set()
    for path in sorted((SOURCES / "snowflake/activity").rglob("*.parquet")):
        rel = path.relative_to(SOURCES).as_posix()
        table = pq.read_table(path)
        result = _validate(
            table,
            source="snowflake",
            table_name="activity",
            source_file=rel,
            model=SnowflakeActivity,
            warehouse=warehouse,
        )
        assert len(result.valid_rows) + len(result.rejected_rows) == len(table)
        found.update((rel, row.source_row, row.rule_id) for row in result.rejected_rows)
    for path in sorted((SOURCES / "teradata").glob("client_*.csv")):
        rel = path.relative_to(SOURCES).as_posix()
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            rows = list(reader)
            table = pa.table(
                {name: [row[name] for row in rows] for name in reader.fieldnames or []}
            )
        result = _validate(
            table,
            source="teradata",
            table_name="CLNT",
            source_file=rel,
            model=TeradataClient,
            warehouse=warehouse,
            allow_text_coercion=True,
        )
        assert len(result.valid_rows) + len(result.rejected_rows) == len(table)
        found.update((rel, row.source_row, row.rule_id) for row in result.rejected_rows)
    assert found == wanted
    assert len(meta.get_rejected_rows(warehouse)) == len(wanted)


def test_missing_column_and_type_change_fail_with_dq006(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    table = pq.read_table(next((SOURCES / "snowflake/activity").rglob("*.parquet")))
    for drifted in (
        table.drop_columns(["ACTIVITY_ID"]),
        table.set_column(
            table.schema.get_field_index("DURATION_MIN"),
            "DURATION_MIN",
            pa.array(["12"] * len(table)),
        ),
    ):
        with pytest.raises(SchemaDriftError, match="DQ006"):
            _validate(
                drifted,
                source="snowflake",
                table_name="activity",
                source_file="snowflake/activity/drifted.parquet",
                model=SnowflakeActivity,
                warehouse=warehouse,
            )
    assert meta.get_watermark(warehouse, "snowflake", "activity") is None
    assert meta.get_rejected_rows(warehouse) == []


def test_additive_column_records_warn_and_keeps_contract_columns(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    table = pq.read_table(next((SOURCES / "snowflake/activity").rglob("*.parquet")))
    table = table.append_column("EXTRA_NOTE", pa.array(["x"] * len(table)))
    result = _validate(
        table,
        source="snowflake",
        table_name="activity",
        source_file="snowflake/activity/extra.parquet",
        model=SnowflakeActivity,
        warehouse=warehouse,
    )
    assert "EXTRA_NOTE" not in result.valid_rows.column_names
    assert result.warnings == ("Extra columns ignored: EXTRA_NOTE",)
    check = meta.get_check_results(warehouse, "run-1")
    assert len(check) == 1 and check[0].check_id == "DQ006"
    assert check[0].status is CheckStatus.WARN


def test_100k_rows_validate_within_two_seconds() -> None:
    path = next((SOURCES / "snowflake/activity").rglob("*.parquet"))
    row = pq.read_table(path).slice(0, 1)
    table = pa.concat_tables([row] * 100_000).combine_chunks()
    start = time.perf_counter()
    result = _validate(
        table,
        source="snowflake",
        table_name="activity",
        source_file="snowflake/activity/benchmark.parquet",
        model=SnowflakeActivity,
    )
    elapsed = time.perf_counter() - start
    assert len(result.valid_rows) == 100_000
    assert not result.rejected_rows
    assert elapsed < 2, f"Validation took {elapsed:.2f}s"


def test_naive_text_timestamps_are_read_as_utc() -> None:
    """PLAN.md §6.2. Run under TZ=Asia/Tokyo too: a local session zone would shift this."""
    path = sorted((SOURCES / "teradata").glob("client_*.csv"))[-1]
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        table = pa.table({name: [row[name] for row in rows] for name in reader.fieldnames or []})
    result = _validate(
        table,
        source="teradata",
        table_name="CLNT",
        source_file=path.name,
        model=TeradataClient,
        allow_text_coercion=True,
    )
    valid_ids = set(result.valid_rows.column("CLNT_ID").to_pylist())
    raw = {r["CLNT_ID"]: r["LAST_UPD_TS"] for r in rows if r["CLNT_ID"] in valid_ids}
    loaded = dict(
        zip(
            result.valid_rows.column("CLNT_ID").to_pylist(),
            result.valid_rows.column("LAST_UPD_TS").to_pylist(),
            strict=True,
        )
    )
    assert raw
    for client_id, text in raw.items():
        expected = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        assert loaded[client_id] == expected


def test_drift_warnings_from_several_files_share_one_check_row(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    table = pq.read_table(next((SOURCES / "snowflake/activity").rglob("*.parquet")))
    table = table.append_column("EXTRA_NOTE", pa.array(["x"] * len(table)))
    for name in ("a.parquet", "b.parquet", "b.parquet"):
        _validate(
            table,
            source="snowflake",
            table_name="activity",
            source_file=name,
            model=SnowflakeActivity,
            warehouse=warehouse,
        )
    (check,) = meta.get_check_results(warehouse, "run-1")
    assert check.observed == 2
    assert check.message == (
        "a.parquet: Extra columns ignored: EXTRA_NOTE; b.parquet: Extra columns ignored: EXTRA_NOTE"
    )
