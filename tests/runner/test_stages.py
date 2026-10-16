from __future__ import annotations

import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pulse.contracts.enums import RunType, StageStatus
from pulse.ingest import meta
from pulse.runner import (
    WEEKLY_STAGES,
    Runner,
    Stage,
    StageContext,
    StageResult,
    WarehouseSink,
    stages,
)
from pulse.runner.stage import not_implemented
from pulse.warehouse import WAREHOUSE_FILE, connect, init_warehouse

WEEK = "2026-W40"
T0 = datetime(2026, 10, 5, 11, 0, tzinfo=UTC)
FIXTURE_SOURCES = Path(__file__).parents[2] / "fixtures" / "sources"


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def now(self) -> datetime:
        self.t += timedelta(milliseconds=10)
        return self.t

    def sleep(self, seconds: float) -> None:
        pass


def ctx(data_dir: Path, run_id: str = f"manual-{WEEK}-1") -> StageContext:
    return StageContext(run_id, RunType.MANUAL, WEEK, data_dir, Clock())


def pipeline(**fns: object) -> list[Stage]:
    """Weekly DAG from dbt_build on; other stages are placeholders unless overridden."""
    keep = {"dbt_build", "checks", "export"}
    return [
        replace(s, fn=fns.get(s.name, s.fn if s.name in keep else not_implemented(0)))  # type: ignore[arg-type]
        for s in WEEKLY_STAGES
    ]


def run(data_dir: Path, stage_list: Sequence[Stage]) -> dict[str, StageResult | StageStatus]:
    warehouse = data_dir / WAREHOUSE_FILE
    runner = Runner(stage_list, data_dir=data_dir, sinks=[WarehouseSink(warehouse)], clock=Clock())
    report = runner.run(WEEK, RunType.MANUAL, f"manual-{WEEK}-1")
    finals = {r.stage: r for r in report.rows}
    return {"run": report.status, **{k: v.status for k, v in finals.items()}}  # type: ignore[dict-item]


def fake_dbt(results: list[dict[str, str]], exit_code: int) -> stages.DbtCommand:
    """A dbt stand-in that writes run_results.json and exits like dbt would."""

    def command(ctx: StageContext, target_path: Path) -> list[str]:
        payload = json.dumps({"results": results})
        script = (
            "import pathlib, sys; p = pathlib.Path(sys.argv[1]); "
            "p.mkdir(parents=True, exist_ok=True); "
            "(p / 'run_results.json').write_text(sys.argv[2]); sys.exit(int(sys.argv[3]))"
        )
        return [sys.executable, "-c", script, str(target_path), payload, str(exit_code)]

    return command


# ── dbt_build ───────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_dbt_build_on_fixtures_passes(tmp_path: Path) -> None:
    sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
    from ci_warehouse import build

    build(FIXTURE_SOURCES, tmp_path / WAREHOUSE_FILE)
    result = stages.dbt_build(ctx(tmp_path))
    # Fixtures inject unknown-client defects; DQ013 relationships tests warn by design.
    assert result.status in {StageStatus.SUCCESS, StageStatus.WARN}, result.message
    assert (result.rows_out or 0) > 50
    con = connect(tmp_path / WAREHOUSE_FILE, read_only=True)
    try:
        assert con.execute("select count(*) from staging.stg_activity").fetchone()[0] > 0  # type: ignore[index]
    finally:
        con.close()


def test_failing_dbt_test_fails_the_stage_and_blocks_downstream(tmp_path: Path) -> None:
    bad = fake_dbt(
        [
            {"unique_id": "model.advisor_pulse.stg_activity", "status": "success"},
            {"unique_id": "test.advisor_pulse.unique_stg_activity_activity_id", "status": "fail"},
        ],
        exit_code=1,
    )
    result = stages.dbt_build(ctx(tmp_path), command=bad)
    assert result.status is StageStatus.FAILED
    assert result.message == "dbt build failed: unique_stg_activity_activity_id."

    statuses = run(tmp_path, pipeline(dbt_build=lambda c: stages.dbt_build(c, command=bad)))
    assert statuses["dbt_build"] is StageStatus.FAILED
    assert statuses["checks"] is StageStatus.SKIPPED
    assert statuses["export"] is StageStatus.WARN  # always: run_log.json only
    assert statuses["run"] is StageStatus.FAILED
    assert sorted(p.name for p in stages.export_dir().iterdir()) == ["run_log.json"]


def test_dbt_warnings_make_the_stage_warn(tmp_path: Path) -> None:
    warn = fake_dbt(
        [
            {"unique_id": "model.advisor_pulse.stg_client", "status": "success"},
            {
                "unique_id": "test.advisor_pulse.relationships_stg_activity_client_id",
                "status": "warn",
            },
        ],
        exit_code=0,
    )
    result = stages.dbt_build(ctx(tmp_path), command=warn)
    assert result.status is StageStatus.WARN
    assert "1 warned: relationships_stg_activity_client_id" in (result.message or "")


def test_dbt_crash_before_any_node_fails_with_its_output(tmp_path: Path) -> None:
    def crash(ctx: StageContext, target_path: Path) -> list[str]:
        return [sys.executable, "-c", "import sys; print('Profile not found'); sys.exit(2)"]

    result = stages.dbt_build(ctx(tmp_path), command=crash)
    assert result.status is StageStatus.FAILED
    assert "exited 2" in (result.message or "") and "Profile not found" in (result.message or "")


# ── checks ──────────────────────────────────────────────────────────────────


def test_checks_and_export_skip_until_marts_exist(tmp_path: Path) -> None:
    ok = fake_dbt([], exit_code=0)
    statuses = run(tmp_path, pipeline(dbt_build=lambda c: stages.dbt_build(c, command=ok)))
    assert statuses["checks"] is StageStatus.SKIPPED
    assert statuses["export"] is StageStatus.SKIPPED
    assert not stages.export_dir().exists()


def _org_mart(data_dir: Path) -> None:
    """A minimal mart_org_weekly: enough for run_checks, nothing loaded into raw."""
    con = connect(data_dir / WAREHOUSE_FILE)
    try:
        init_warehouse(con)
        con.execute("create schema if not exists marts")
        con.execute(
            "create table marts.mart_org_weekly as select "
            "'2026-W40' as iso_week_id, 'NATIONAL' as level, 'CA' as node_id, "
            "100 as activities_completed"
        )
    finally:
        con.close()


def test_fail_check_fails_the_stage_and_blocks_export_data(tmp_path: Path) -> None:
    _org_mart(tmp_path)
    ok = fake_dbt([], exit_code=0)
    statuses = run(tmp_path, pipeline(dbt_build=lambda c: stages.dbt_build(c, command=ok)))
    # Nothing in raw: DQ030 freshness has no activity date and FAILs.
    assert statuses["checks"] is StageStatus.FAILED
    assert statuses["export"] is StageStatus.WARN
    assert sorted(p.name for p in stages.export_dir().iterdir()) == ["run_log.json"]

    con = connect(tmp_path / WAREHOUSE_FILE, read_only=True)
    try:
        results = meta.get_check_results(con, f"manual-{WEEK}-1")
    finally:
        con.close()
    assert {c.check_id for c in results} == {"DQ030", "DQ031", "DQ032", "DQ033"}
    run_log = json.loads((stages.export_dir() / "run_log.json").read_text())
    assert run_log["runs"][0]["run_id"] == f"manual-{WEEK}-1"
    assert run_log["runs"][0]["status"] == "FAILED"


def test_missing_defects_file_means_an_empty_manifest(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="pulse.runner.stages"):
        manifest = stages.load_defects(tmp_path, WEEK, T0)
    assert manifest.defects == []
    assert [str(w) for w in manifest.iso_weeks] == [WEEK]
    assert "No defects.json" in caplog.text


def test_defects_file_is_read_when_present(tmp_path: Path) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "defects.json"
    (tmp_path / "defects.json").write_text(fixture.read_text())
    assert stages.load_defects(tmp_path, WEEK, T0).defects


# ── wiring ──────────────────────────────────────────────────────────────────


def test_weekly_dag_uses_the_real_stages() -> None:
    by_name = {s.name: s for s in WEEKLY_STAGES}
    assert by_name["dbt_build"].fn is stages.dbt_build
    assert by_name["checks"].fn is stages.checks
    assert by_name["export"].fn is stages.export
    assert by_name["export"].always


def test_cold_rebuild_does_not_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pulse.runner.dag as dag
    from pulse.state import backfill_rebuild

    seen: list[str] = []

    def record(name: str) -> object:
        def fn(c: StageContext) -> StageResult:
            seen.append(name)
            return StageResult()

        return fn

    monkeypatch.setattr(
        dag,
        "WEEKLY_STAGES",
        tuple(replace(s, fn=record(s.name)) for s in WEEKLY_STAGES),  # type: ignore[arg-type]
    )
    result = backfill_rebuild(ctx(tmp_path), ["2026-W39"])
    assert result.status is StageStatus.SUCCESS
    assert seen == ["generate", "ingest", "dbt_build", "checks", "narrate"]
