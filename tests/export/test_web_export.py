"""Web export contract, budget, failure, and determinism checks on fixture marts."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import pytest

from pulse.contracts import arrow_schema
from pulse.contracts.enums import StageStatus
from pulse.contracts.exports import (
    EXPORT_TABLE_CONTRACTS,
    Manifest,
    NarrativeFile,
    PipelineGraph,
    RunLogExport,
)
from pulse.export.publish import ExportBudgetError
from pulse.export.web import export_web
from pulse.warehouse import connect

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/exports"
GENERATED_AT = datetime(2026, 10, 5, 12, tzinfo=UTC)


@pytest.fixture
def warehouse() -> Iterator[duckdb.DuckDBPyConnection]:
    con = connect(":memory:")
    con.execute("CREATE SCHEMA marts")
    for model in EXPORT_TABLE_CONTRACTS:
        name = model.contract_name
        con.execute(
            f"CREATE TABLE marts.mart_{name} AS SELECT * FROM read_parquet(?)",
            [str(FIXTURES / f"{name}.parquet")],
        )
    yield con
    con.close()


def _documents() -> tuple[RunLogExport, PipelineGraph, dict[str, NarrativeFile]]:
    log = RunLogExport.model_validate_json((FIXTURES / "run_log.json").read_text())
    graph = PipelineGraph.model_validate_json((FIXTURES / "pipeline_graph.json").read_text())
    narrative = NarrativeFile.model_validate_json(
        (FIXTURES / "narratives/2026-W40.json").read_text()
    )
    return log, graph, {"2026-W40": narrative}


def _export(con: duckdb.DuckDBPyConnection, root: Path, **options: int):
    log, graph, narratives = _documents()
    return export_web(
        con,
        root,
        run_log=log,
        pipeline_graph=graph,
        narratives=narratives,
        run_id="test-run",
        generated_at=GENERATED_AT,
        **options,
    )


def _bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_export_matches_contracts_and_manifest_checksums(
    warehouse: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    root = tmp_path / "data"
    manifest = _export(warehouse, root)

    assert manifest == Manifest.model_validate_json((root / "manifest.json").read_text())
    assert manifest.latest_week == "2026-W40"
    assert manifest.summary
    assert manifest.files
    for entry in manifest.files:
        path = root / entry.name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry.sha256
        assert path.stat().st_size == entry.bytes
    for model in EXPORT_TABLE_CONTRACTS:
        table = pq.ParquetFile(root / f"{model.contract_name}.parquet").read()
        assert table.schema == arrow_schema(model)
        assert len(table) > 0


def test_export_bytes_repeat_for_same_state(
    warehouse: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    root = tmp_path / "data"
    _export(warehouse, root)
    first = _bytes(root)
    _export(warehouse, root)
    assert _bytes(root) == first


def test_tiny_budget_rejects_without_changing_existing_files(
    warehouse: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    root = tmp_path / "data"
    _export(warehouse, root)
    first = _bytes(root)
    with pytest.raises(ExportBudgetError):
        _export(warehouse, root, max_file_bytes=1, max_total_bytes=100)
    assert _bytes(root) == first


def test_failed_run_changes_only_run_log(
    warehouse: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    root = tmp_path / "data"
    _export(warehouse, root)
    first = _bytes(root)
    log, graph, narratives = _documents()
    failed = log.model_copy(
        update={
            "runs": [log.runs[0].model_copy(update={"status": StageStatus.FAILED}), *log.runs[1:]]
        }
    )

    with pytest.raises(ExportBudgetError):
        export_web(
            warehouse,
            root,
            run_log=failed,
            pipeline_graph=graph,
            narratives=narratives,
            run_id="failed-run",
            generated_at=GENERATED_AT,
            max_total_bytes=1,
            max_file_bytes=1,
        )
    assert _bytes(root) == first

    result = export_web(
        warehouse,
        root,
        run_log=failed,
        pipeline_graph=graph,
        narratives=narratives,
        run_id="failed-run",
        generated_at=GENERATED_AT,
    )

    assert result is None
    after = _bytes(root)
    assert after["run_log.json"] != first["run_log.json"]
    assert {k: v for k, v in after.items() if k != "run_log.json"} == {
        k: v for k, v in first.items() if k != "run_log.json"
    }
    _export(warehouse, root)
    assert _bytes(root) == first


def test_export_uses_calendar_week_windows(
    warehouse: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    for offset in range(1, 35):
        monday = date(2026, 9, 28) - timedelta(weeks=offset)
        week = f"{monday.isocalendar().year}-W{monday.isocalendar().week:02d}"
        for name in ("advisor_weekly", "geo_weekly"):
            warehouse.execute(
                f"INSERT INTO marts.mart_{name} "
                f"SELECT * REPLACE (? AS iso_week_id) FROM marts.mart_{name} "
                "WHERE iso_week_id = '2026-W40'",
                [week],
            )
    _export(warehouse, tmp_path / "data")
    advisor = pq.read_table(tmp_path / "data/advisor_weekly.parquet").column("iso_week_id")
    geo = pq.read_table(tmp_path / "data/geo_weekly.parquet").column("iso_week_id")
    assert len(set(advisor.to_pylist())) == 26
    assert len(set(geo.to_pylist())) == 13
