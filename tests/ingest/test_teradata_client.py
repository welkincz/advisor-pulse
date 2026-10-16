"""SQLite CLNT snapshot ingestion against committed source fixtures."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from pulse.contracts.enums import LoadStatus, StageStatus
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


def test_snapshot_matches_fixture_and_rerun_is_no_op(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    with sqlite3.connect(sources / "teradata/edw.sqlite") as db:
        expected = db.execute("SELECT count(*) FROM CLNT").fetchone()[0]
    result = _load(warehouse, sources)
    assert result.status is StageStatus.SUCCESS
    assert result.rows_in == result.rows_out == expected
    assert warehouse.execute("SELECT count(*) FROM raw.teradata__clnt").fetchone()[0] == expected
    manifest = meta.get_manifest(warehouse, "teradata/edw.sqlite#clnt")
    assert len(manifest) == 1
    assert manifest[0].status is LoadStatus.LOADED
    assert meta.get_watermark(warehouse, "teradata", "CLNT") is not None

    assert _load(warehouse, sources, "run-2").status is StageStatus.SKIPPED
    assert warehouse.execute("SELECT count(*) FROM raw.teradata__clnt").fetchone()[0] == expected
    assert len(meta.get_manifest(warehouse)) == 1


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
    assert warehouse.execute("SELECT count(*) FROM raw.teradata__clnt").fetchone()[0] == 0


def test_snapshot_insert_failure_rolls_back_manifest_and_watermark(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    warehouse.execute("DROP TABLE raw.teradata__clnt")
    with pytest.raises(duckdb.Error):
        _load(warehouse, sources)
    assert meta.get_manifest(warehouse) == []
    assert meta.get_watermark(warehouse, "teradata", "CLNT") is None
    assert meta.get_rejected_rows(warehouse) == []
