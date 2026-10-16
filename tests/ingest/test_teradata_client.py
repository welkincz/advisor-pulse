"""Client snapshot and delta ingestion against committed source and defect fixtures."""

from __future__ import annotations

import csv
import shutil
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

from pulse.contracts.defects import DefectManifest
from pulse.contracts.enums import LoadStatus, StageStatus
from pulse.contracts.sources import TeradataClient
from pulse.ingest import meta
from pulse.ingest.teradata_client import load_teradata_client
from pulse.warehouse import connect, init_warehouse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
LOADED_AT = datetime(2026, 10, 5, 12, tzinfo=UTC)


@pytest.fixture
def warehouse() -> Iterator[duckdb.DuckDBPyConnection]:
    con = connect(":memory:")
    init_warehouse(con)
    yield con
    con.close()


@pytest.fixture
def sources(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    shutil.copytree(FIXTURES / "sources/teradata", root / "teradata")
    return root


def _load(con: duckdb.DuckDBPyConnection, root: Path, run_id: str = "run-1"):
    return load_teradata_client(con, root, run_id=run_id, loaded_at=LOADED_AT)


def _raw_count(con: duckdb.DuckDBPyConnection) -> int:
    return con.execute("SELECT count(*) FROM raw.teradata__clnt").fetchone()[0]


def test_fixture_final_state_and_exact_quarantine(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    result = _load(warehouse, sources)
    expected: dict[str, TeradataClient] = {}
    with sqlite3.connect(sources / "teradata/edw.sqlite") as db:
        db.row_factory = sqlite3.Row
        for row in db.execute("SELECT * FROM CLNT"):
            client = TeradataClient.model_validate(dict(row))
            expected[client.client_id] = client
    for path in sorted((sources / "teradata").glob("client_*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                try:
                    client = TeradataClient.model_validate({k: v or None for k, v in row.items()})
                except ValidationError:
                    continue
                expected[client.client_id] = client

    cursor = warehouse.execute(
        "SELECT * EXCLUDE (_batch_id, _source_file, _source_row, _row_hash, _loaded_at, rn) "
        "FROM (SELECT *, row_number() OVER "
        "(PARTITION BY CLNT_ID ORDER BY LAST_UPD_TS DESC) rn "
        "FROM raw.teradata__clnt) WHERE rn = 1"
    )
    names = [column[0] for column in cursor.description]
    actual = {
        client.client_id: client
        for client in (
            TeradataClient.model_validate(dict(zip(names, row, strict=True)))
            for row in cursor.fetchall()
        )
    }
    assert actual == {
        key: client.model_copy(
            update={"last_updated_ts": client.last_updated_ts.replace(tzinfo=UTC)}
        )
        for key, client in expected.items()
    }
    defects = DefectManifest.model_validate_json((FIXTURES / "defects.json").read_text())
    expected_rejects = {
        (d.file, d.row, d.rule_id)
        for d in defects.defects
        if d.source == "teradata" and d.table_name == "CLNT" and d.rule_id == "DQ005"
    }
    assert {
        (r.source_file, r.source_row, r.rule_id) for r in meta.get_rejected_rows(warehouse)
    } == expected_rejects
    assert result.status is StageStatus.SUCCESS
    assert result.rows_quarantined == len(expected_rejects)
    assert len(meta.get_manifest(warehouse)) == 6


def test_rerun_is_no_op_and_older_delta_is_logged(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    _load(warehouse, sources)
    count = _raw_count(warehouse)
    assert _load(warehouse, sources, "run-2").status is StageStatus.SKIPPED
    assert _raw_count(warehouse) == count
    assert len(meta.get_manifest(warehouse)) == 6

    path = sources / "teradata/client_20260909.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    result = _load(warehouse, sources, "run-3")
    assert result.rows_out == 0
    assert "1 had no new rows after the watermark" in (result.message or "")
    assert _raw_count(warehouse) == count
    versions = meta.get_manifest(warehouse, "teradata/client_20260909.csv")
    assert len(versions) == 2
    assert versions[-1].rows_loaded == 0


def test_malformed_csv_record_is_quarantined_without_aborting_later_rows(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    path = sources / "teradata/client_20261004.csv"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("CLI-99999999,2026-10-04,1990\n")
        handle.write('CLI-99999997,2026-10-04,1990,MASS,"unclosed\n')
        handle.write(
            'CLI-99999998,2026-10-04,1990,MASS,"M5V, 1A1",ON,ADV-10001,BR-0101,A,'
            "2026-10-04 14:00:00\n"
        )
    result = _load(warehouse, sources)
    assert result.status is StageStatus.SUCCESS
    assert result.rows_quarantined >= 4
    assert warehouse.execute(
        "SELECT PSTL_CD FROM raw.teradata__clnt WHERE CLNT_ID = 'CLI-99999998'"
    ).fetchone() == ("M5V, 1A1",)
    assert any(
        r.source_file == "teradata/client_20261004.csv"
        and r.rule_id == "DQ005"
        and "CLI-99999999" in r.payload
        for r in meta.get_rejected_rows(warehouse)
    )
    assert any(
        r.source_file == "teradata/client_20261004.csv"
        and r.rule_id == "DQ005"
        and "unclosed" in r.payload
        for r in meta.get_rejected_rows(warehouse)
    )


def test_additive_csv_column_records_dq006_warning(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    path = sources / "teradata/client_20261004.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*rows[0], "EXTRA_NOTE"])
        writer.writeheader()
        writer.writerows({**row, "EXTRA_NOTE": "synthetic"} for row in rows)

    _load(warehouse, sources)

    assert any(
        check.check_id == "DQ006" and "EXTRA_NOTE" in (check.message or "")
        for check in meta.get_check_results(warehouse, "run-1")
    )


def test_missing_delta_column_fails_only_that_file(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    path = sources / "teradata/client_20260928.csv"
    original = path.read_bytes()
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    fields = [name for name in rows[0] if name != "BRTH_YR"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({name: row[name] for name in fields} for row in rows)

    result = _load(warehouse, sources)

    assert result.status is StageStatus.WARN
    assert "client_20260928.csv" in (result.message or "")
    assert (
        meta.get_manifest(warehouse, "teradata/client_20260928.csv")[0].status is LoadStatus.FAILED
    )
    assert (
        meta.get_manifest(warehouse, "teradata/client_20261004.csv")[0].status is LoadStatus.LOADED
    )

    path.write_bytes(original)
    recovered = _load(warehouse, sources, "run-2")
    assert recovered.rows_out > 0
    assert (
        warehouse.execute(
            "SELECT count(*) FROM raw.teradata__clnt "
            "WHERE _source_file = 'teradata/client_20260928.csv'"
        ).fetchone()[0]
        > 0
    )
    count = _raw_count(warehouse)
    path.write_bytes(path.read_bytes() + b"\n")
    later = _load(warehouse, sources, "run-3")
    assert later.rows_out == 0
    assert _raw_count(warehouse) == count


def test_sqlite_declared_type_drift_fails_snapshot(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    path = sources / "teradata/edw.sqlite"
    with sqlite3.connect(path) as db:
        ddl = db.execute("SELECT sql FROM sqlite_master WHERE name = 'CLNT'").fetchone()[0]
        db.execute("ALTER TABLE CLNT RENAME TO CLNT_old")
        db.execute(ddl.replace('"BRTH_YR" INTEGER', '"BRTH_YR" TEXT'))
        db.execute("INSERT INTO CLNT SELECT * FROM CLNT_old")
        db.execute("DROP TABLE CLNT_old")

    result = _load(warehouse, sources)

    assert result.status is StageStatus.FAILED
    assert meta.get_manifest(warehouse, "teradata/edw.sqlite#clnt")[0].status is LoadStatus.FAILED
    assert meta.get_manifest(warehouse, "teradata/client_20260909.csv") == []


def test_snapshot_insert_failure_rolls_back_manifest_and_watermark(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    warehouse.execute("DROP TABLE raw.teradata__clnt")
    with pytest.raises(duckdb.Error):
        _load(warehouse, sources)
    assert meta.get_manifest(warehouse) == []
    assert meta.get_watermark(warehouse, "teradata", "CLNT") is None
    assert meta.get_rejected_rows(warehouse) == []
