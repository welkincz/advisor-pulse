"""The HR SQLite fixture is the source of truth for incremental load tests."""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from pulse.ingest import meta
from pulse.ingest.teradata_hr import load_teradata_hr
from pulse.warehouse import connect, init_warehouse

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/sources/teradata/edw.sqlite"
LOADED_AT = datetime(2026, 10, 5, 12, tzinfo=UTC)
TABLES = {"ADVSR": 20, "ADVSR_ASGN": 26, "BRNCH": 6}


@pytest.fixture
def warehouse() -> Iterator[duckdb.DuckDBPyConnection]:
    con = connect(":memory:")
    init_warehouse(con)
    yield con
    con.close()


@pytest.fixture
def source_db(tmp_path: Path) -> Path:
    path = tmp_path / "edw.sqlite"
    shutil.copyfile(FIXTURE, path)
    return path


def _counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    return {
        table: con.execute(f"SELECT count(*) FROM raw.teradata__{table.lower()}").fetchone()[0]
        for table in TABLES
    }


def test_fixture_loads_three_contract_tables_and_watermarks(
    warehouse: duckdb.DuckDBPyConnection, source_db: Path
) -> None:
    result = load_teradata_hr(warehouse, source_db, run_id="run-1", loaded_at=LOADED_AT)

    assert (result.rows_read, result.rows_loaded, result.skipped) == (52, 52, False)
    assert _counts(warehouse) == TABLES
    assert meta.get_watermark_value(warehouse, "teradata", "ADVSR") == datetime(
        2026, 9, 25, 15, tzinfo=UTC
    )
    assert meta.get_watermark_value(warehouse, "teradata", "ADVSR_ASGN") == datetime(
        2026, 9, 25, 15, tzinfo=UTC
    )
    assert meta.get_watermark_value(warehouse, "teradata", "BRNCH") == datetime(
        2026, 1, 5, 14, tzinfo=UTC
    )
    manifest = meta.get_manifest(warehouse)
    assert len(manifest) == 1
    assert (manifest[0].file_path, manifest[0].row_count, manifest[0].rows_loaded) == (
        "teradata/edw.sqlite#hr",
        52,
        52,
    )
    assert warehouse.execute(
        "SELECT DISTINCT _source_file FROM raw.teradata__advsr"
    ).fetchall() == [("teradata/edw.sqlite",)]


def test_same_file_rerun_is_no_op(warehouse: duckdb.DuckDBPyConnection, source_db: Path) -> None:
    load_teradata_hr(warehouse, source_db, run_id="run-1", loaded_at=LOADED_AT)
    result = load_teradata_hr(warehouse, source_db, run_id="run-2", loaded_at=LOADED_AT)

    assert result.skipped and result.rows_loaded == 0
    assert _counts(warehouse) == TABLES
    assert len(meta.get_manifest(warehouse)) == 1
    assert meta.get_watermark(warehouse, "teradata", "ADVSR").run_id == "run-1"


def test_changed_snapshot_loads_only_newer_rows(
    warehouse: duckdb.DuckDBPyConnection, source_db: Path
) -> None:
    load_teradata_hr(warehouse, source_db, run_id="run-1", loaded_at=LOADED_AT)
    with sqlite3.connect(source_db) as source:
        source.execute(
            "UPDATE ADVSR SET ROLE_CD = 'SNR_ADVSR', LAST_UPD_TS = '2026-10-06 12:00:00' "
            "WHERE ADVSR_ID = 'ADV-10001'"
        )
        source.execute(
            "UPDATE ADVSR_ASGN SET LAST_UPD_TS = '2026-10-06 12:00:00' "
            "WHERE ASGN_ID = 'ASG-00000001'"
        )
        source.execute(
            "UPDATE BRNCH SET BRNCH_NM = 'King & Bay East Branch', "
            "LAST_UPD_TS = '2026-10-06 12:00:00' WHERE BRNCH_ID = 'BR-0101'"
        )

    result = load_teradata_hr(warehouse, source_db, run_id="run-2", loaded_at=LOADED_AT)

    assert (result.rows_read, result.rows_loaded, result.skipped) == (52, 3, False)
    assert _counts(warehouse) == {table: count + 1 for table, count in TABLES.items()}
    assert len(meta.get_manifest(warehouse)) == 2
    for table in TABLES:
        assert meta.get_watermark_value(warehouse, "teradata", table) == datetime(
            2026, 10, 6, 12, tzinfo=UTC
        )


def test_new_row_at_watermark_boundary_is_loaded(
    warehouse: duckdb.DuckDBPyConnection, source_db: Path
) -> None:
    load_teradata_hr(warehouse, source_db, run_id="run-1", loaded_at=LOADED_AT)
    with sqlite3.connect(source_db) as source:
        source.execute(
            "INSERT INTO ADVSR_ASGN SELECT 'ASG-00000027', ADVSR_ID, BRNCH_ID, "
            "ROLE_CD, EFF_DT, RSN_CD, LAST_UPD_TS FROM ADVSR_ASGN "
            "WHERE ASGN_ID = 'ASG-00000026'"
        )

    result = load_teradata_hr(warehouse, source_db, run_id="run-2", loaded_at=LOADED_AT)

    assert result.rows_loaded == 1
    assert _counts(warehouse)["ADVSR_ASGN"] == 27
    assert warehouse.execute(
        "SELECT count(*) FROM raw.teradata__advsr_asgn WHERE ASGN_ID = 'ASG-00000027'"
    ).fetchone() == (1,)
    assert len(meta.get_manifest(warehouse)) == 2


def test_additive_source_column_warns_and_does_not_fail(
    warehouse: duckdb.DuckDBPyConnection, source_db: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with sqlite3.connect(source_db) as source:
        source.execute("ALTER TABLE BRNCH ADD COLUMN OPTIONAL_NOTE TEXT")
        source.execute("UPDATE BRNCH SET OPTIONAL_NOTE = 'synthetic note'")

    with caplog.at_level(logging.WARNING, logger="pulse.ingest.teradata_hr"):
        result = load_teradata_hr(warehouse, source_db, run_id="run-1", loaded_at=LOADED_AT)

    assert result.rows_loaded == 52
    assert _counts(warehouse) == TABLES
    assert "BRNCH additive columns ignored: OPTIONAL_NOTE" in caplog.text


def test_invalid_contract_row_does_not_write_any_table(
    warehouse: duckdb.DuckDBPyConnection, source_db: Path
) -> None:
    with sqlite3.connect(source_db) as source:
        source.execute("UPDATE ADVSR SET ROLE_CD = 'INVALID' WHERE ADVSR_ID = 'ADV-10001'")

    with pytest.raises(ValueError, match="ROLE_CD"):
        load_teradata_hr(warehouse, source_db, run_id="run-1", loaded_at=LOADED_AT)

    assert _counts(warehouse) == {table: 0 for table in TABLES}
    assert meta.get_manifest(warehouse) == []
    assert all(meta.get_watermark(warehouse, "teradata", table) is None for table in TABLES)


def test_late_insert_failure_rolls_back_all_three_tables(
    warehouse: duckdb.DuckDBPyConnection, source_db: Path
) -> None:
    warehouse.execute("DROP TABLE raw.teradata__brnch")

    with pytest.raises(duckdb.Error):
        load_teradata_hr(warehouse, source_db, run_id="run-1", loaded_at=LOADED_AT)

    assert warehouse.execute("SELECT count(*) FROM raw.teradata__advsr").fetchone() == (0,)
    assert warehouse.execute("SELECT count(*) FROM raw.teradata__advsr_asgn").fetchone() == (0,)
    assert meta.get_manifest(warehouse) == []
    assert all(meta.get_watermark(warehouse, "teradata", table) is None for table in TABLES)
