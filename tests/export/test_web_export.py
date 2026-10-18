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
from pulse.runner.stages import load_narratives
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


def _full_template(week: str) -> NarrativeFile:
    """Fixture-derived 18-node narrative near the size of a real-scale template week."""
    source = _documents()[2]["2026-W40"]
    nodes = []
    for index in range(18):
        base = source.narratives[index % len(source.narratives)]
        facts = [
            base.facts_used[j % len(base.facts_used)].model_copy(update={"fact_id": f"F{j + 1}"})
            for j in range(60)
        ]
        nodes.append(
            base.model_copy(
                update={
                    "node_id": f"SYN-{index:02d}",
                    "facts_used": facts,
                    "fallback": True,
                    "model": None,
                }
            )
        )
    return source.model_copy(update={"iso_week_id": week, "narratives": nodes})


def _narrative_weeks(count: int) -> list[str]:
    monday = date(2026, 9, 28)
    return [
        f"{(monday - timedelta(weeks=i)).isocalendar().year}-W"
        f"{(monday - timedelta(weeks=i)).isocalendar().week:02d}"
        for i in range(count)
    ]


def test_export_keeps_only_latest_26_of_60_local_narrative_weeks(
    warehouse: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    log, graph, _ = _documents()
    weeks = _narrative_weeks(60)
    folder = tmp_path / "local" / "narratives"
    folder.mkdir(parents=True)
    for week in weeks:
        (folder / f"{week}.json").write_text(_full_template(week).model_dump_json(indent=2))
    manifest = export_web(
        warehouse,
        tmp_path / "site",
        run_log=log,
        pipeline_graph=graph,
        narratives=load_narratives(tmp_path / "local"),
        run_id="test-run",
        generated_at=GENERATED_AT,
    )
    published = sorted(f.name for f in manifest.files if f.name.startswith("narratives/"))
    assert published == sorted(f"narratives/{week}.json" for week in weeks[:26])
    assert len(list(folder.glob("*.json"))) == 60
    saved_manifest = Manifest.model_validate_json((tmp_path / "site/manifest.json").read_text())
    saved_names = sorted(f.name for f in saved_manifest.files if f.name.startswith("narratives/"))
    assert saved_names == published
    assert b"\n  " not in (tmp_path / "site" / published[0]).read_bytes()


def test_104_real_size_template_weeks_fit_export_budget(
    warehouse: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    log, graph, _ = _documents()
    weeks = _narrative_weeks(104)
    full = _full_template(weeks[0])
    assert len(full.model_dump_json(indent=2).encode()) > 250_000
    narratives = {week: full.model_copy(update={"iso_week_id": week}) for week in weeks}
    manifest = export_web(
        warehouse,
        tmp_path / "site",
        run_log=log,
        pipeline_graph=graph,
        narratives=narratives,
        run_id="test-run",
        generated_at=GENERATED_AT,
    )
    assert len([f for f in manifest.files if f.name.startswith("narratives/")]) == 26
    assert sum(p.stat().st_size for p in (tmp_path / "site").rglob("*") if p.is_file()) < 20_000_000


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
