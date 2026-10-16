"""Activity ingest behavior against the committed Parquet and defect fixtures."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pulse.contracts.defects import DefectManifest
from pulse.contracts.enums import LoadStatus, StageStatus
from pulse.ingest import meta
from pulse.ingest.snowflake import load_snowflake_activity
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
    shutil.copytree(FIXTURES / "sources/snowflake/activity", root / "snowflake/activity")
    return root


def _load(con: duckdb.DuckDBPyConnection, root: Path, run_id: str = "run-1"):
    return load_snowflake_activity(con, root, run_id=run_id, loaded_at=LOADED_AT)


def _raw_count(con: duckdb.DuckDBPyConnection) -> int:
    return con.execute("SELECT count(*) FROM raw.snowflake__activity").fetchone()[0]


def test_fixture_loads_valid_rows_and_quarantines_exact_defects(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    result = _load(warehouse, sources)
    expected = DefectManifest.model_validate_json((FIXTURES / "defects.json").read_text())
    defects = {
        (d.file, d.row, d.rule_id)
        for d in expected.defects
        if d.source == "snowflake" and d.rule_id in {"DQ001", "DQ002", "DQ003", "DQ004", "DQ005"}
    }

    assert (result.status, result.rows_in, result.rows_out, result.rows_quarantined) == (
        StageStatus.SUCCESS,
        662,
        654,
        8,
    )
    assert _raw_count(warehouse) == 654
    assert len(meta.get_manifest(warehouse)) == 5
    assert meta.get_watermark_value(warehouse, "snowflake", "activity") == datetime(
        2026, 10, 5, 3, tzinfo=UTC
    )
    assert {
        (r.source_file, r.source_row, r.rule_id) for r in meta.get_rejected_rows(warehouse)
    } == defects
    assert warehouse.execute(
        "SELECT count(*) FROM raw.snowflake__activity WHERE _source_file LIKE '%part-001.parquet'"
    ).fetchone() == (87,)


def test_identical_rerun_reports_duplicate_and_does_not_write(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    _load(warehouse, sources)
    result = _load(warehouse, sources, run_id="run-2")

    assert result.status is StageStatus.SKIPPED
    assert result.message == "SKIPPED_DUPLICATE: 5 files"
    assert (result.rows_in, result.rows_out, result.rows_quarantined) == (0, 0, 0)
    assert _raw_count(warehouse) == 654
    assert len(meta.get_manifest(warehouse)) == 5
    assert len(meta.get_rejected_rows(warehouse)) == 8


def test_changed_historical_file_loads_correction_without_watermark_regression(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    _load(warehouse, sources)
    path = sources / "snowflake/activity/extract_date=2026-09-13/part-000.parquet"
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["OUTCOME"] = "FOLLOW_UP" if rows[0]["OUTCOME"] != "FOLLOW_UP" else "NONE"
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)

    result = _load(warehouse, sources, run_id="run-2")

    assert result.rows_out == 1
    assert _raw_count(warehouse) == 655
    assert len(meta.get_manifest(warehouse)) == 6
    versions = meta.get_manifest(
        warehouse, "snowflake/activity/extract_date=2026-09-13/part-000.parquet"
    )
    assert len({entry.file_sha256 for entry in versions}) == 2
    assert meta.get_watermark_value(warehouse, "snowflake", "activity") == datetime(
        2026, 10, 5, 3, tzinfo=UTC
    )


def test_additive_column_is_warned_and_dropped_before_raw_insert(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    path = sources / "snowflake/activity/extract_date=2026-09-13/part-000.parquet"
    table = pq.read_table(path)
    pq.write_table(table.append_column("EXTRA_NOTE", pa.array(["x"] * len(table))), path)

    result = _load(warehouse, sources)

    assert result.rows_out == 654
    assert _raw_count(warehouse) == 654
    assert meta.get_check_results(warehouse, "run-1")[0].check_id == "DQ006"


def test_insert_failure_rolls_back_raw_watermark_manifest_and_quarantine(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    warehouse.execute("DROP TABLE raw.snowflake__activity")
    with pytest.raises(duckdb.Error):
        _load(warehouse, sources)

    assert meta.get_manifest(warehouse) == []
    assert meta.get_watermark(warehouse, "snowflake", "activity") is None
    assert meta.get_rejected_rows(warehouse) == []


def test_schema_drift_fails_one_file_but_later_files_continue(
    warehouse: duckdb.DuckDBPyConnection, sources: Path
) -> None:
    path = sources / "snowflake/activity/extract_date=2026-09-20/part-000.parquet"
    pq.write_table(pq.read_table(path).drop_columns(["ACTIVITY_ID"]), path)

    result = _load(warehouse, sources)

    assert result.status is StageStatus.WARN
    assert result.rows_out == 487
    assert "2026-09-20/part-000.parquet" in (result.message or "")
    assert _raw_count(warehouse) == 487
    assert meta.get_watermark_value(warehouse, "snowflake", "activity") == datetime(
        2026, 10, 5, 3, tzinfo=UTC
    )
    statuses = [entry.status for entry in meta.get_manifest(warehouse)]
    assert statuses.count(LoadStatus.FAILED) == 1
    assert statuses.count(LoadStatus.LOADED) == 4
