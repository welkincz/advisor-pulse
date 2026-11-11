"""End to end: an 8-week backfill from nothing, then one weekly run, on the real DAG.

The backfill ingests and checks each week under its own run, then builds, exports and
persists the whole range once under a single range run (#345). The weekly run that
follows is the full DAG for one week.

The generator runs at the small sizes tests/conftest.py sets, so this takes about a
minute. docs/baseline.md records the same run at default scale over 104 weeks.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pulse.contracts.enums import CheckStatus, RunType, StageStatus
from pulse.contracts.meta import RunLogRow
from pulse.generate.cli import week_range
from pulse.ingest import meta
from pulse.runner.backfill import backfill_range
from pulse.runner.command import run_week
from pulse.runner.dag import WEEKLY_STAGES
from pulse.warehouse import WAREHOUSE_FILE, connect

pytestmark = [pytest.mark.integration, pytest.mark.slow]

FIRST, LAST, NEXT = "2026-W33", "2026-W40", "2026-W41"
DAG_STAGES = [s.name for s in WEEKLY_STAGES]


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 12, 4, tzinfo=UTC)

    def sleep(self, seconds: float) -> None:
        pass


def _assert_dbt_ok(row: RunLogRow, label: str) -> None:
    # At test size a branch has one or two advisors, so a handover often goes to someone
    # at another branch and DQ025 warns. That is the only warning allowed.
    if row.status is not StageStatus.SUCCESS:
        assert row.status is StageStatus.WARN, (label, row.message)
        assert "1 warned: dq025_portfolio_holder_at_another_branch" in (row.message or ""), (
            label,
            row.message,
        )


def test_backfill_then_weekly_run_passes_every_check(tmp_path: Path) -> None:
    lines: list[str] = []
    code = backfill_range(
        FIRST, LAST, data_dir=tmp_path, rebuild=True, clock=Clock(), echo=lines.append
    )
    assert code == 0, "\n".join(lines)
    code = run_week(
        NEXT, data_dir=tmp_path, run_type=RunType.WEEKLY, clock=Clock(), echo=lines.append
    )
    assert code == 0, "\n".join(lines)

    con = connect(tmp_path / WAREHOUSE_FILE, read_only=True)
    try:
        runs = meta.get_run_log(con)
        assert not [r for r in runs if r.status is StageStatus.RUNNING], "a stage never ended"
        by_run: dict[str, dict[str, RunLogRow]] = defaultdict(dict)
        for r in runs:
            assert r.stage not in by_run[r.run_id], ("stage logged twice", r.run_id, r.stage)
            by_run[r.run_id][r.stage] = r
        backfilled = week_range(FIRST, LAST)

        # One range run finalizes the backfill: one dbt build and one export, logged
        # against the last week.
        range_ids = [run_id for run_id in by_run if run_id.startswith("backfill-range-")]
        assert range_ids == [f"backfill-range-{FIRST}-{LAST}-1"], range_ids
        final = by_run[range_ids[0]]
        assert set(final) == set(DAG_STAGES), sorted(final)
        assert {r.iso_week_id for r in final.values()} == {LAST}
        assert final["generate"].status is StageStatus.SUCCESS, final["generate"].message
        assert final["generate"].rows_out == len(backfilled)
        assert final["export"].status is StageStatus.SUCCESS, final["export"].message
        _assert_dbt_ok(final["dbt_build"], "backfill finalize")
        backfill_builds = [
            r for r in runs if r.run_type is RunType.BACKFILL and r.stage in ("dbt_build", "export")
        ]
        assert len(backfill_builds) == 2, [(r.run_id, r.stage) for r in backfill_builds]

        # Every backfilled week ran under its own run: generate, ingest, checks, narrate,
        # and no build, export or state stages of its own.
        week_runs = {
            stages["ingest"].iso_week_id: run_id
            for run_id, stages in by_run.items()
            if run_id not in range_ids and "ingest" in stages
        }
        assert sorted(week_runs) == [*backfilled, NEXT]
        for week in backfilled:
            stages = by_run[week_runs[week]]
            assert set(stages) == {"generate", "ingest", "checks", "narrate"}, (
                week,
                sorted(stages),
            )
            assert {r.iso_week_id for r in stages.values()} == {week}
            for stage in ("generate", "ingest"):
                assert stages[stage].status is StageStatus.SUCCESS, (week, stage)
            assert stages["checks"].status in {StageStatus.SUCCESS, StageStatus.WARN}, week
            if week != LAST:
                # Template narration is the plan for backfilled history, not a warning. The
                # last backfill week tries the model and warns without one.
                assert stages["narrate"].status is StageStatus.SUCCESS, week

        # The weekly run is the full DAG for its own week.
        weekly = by_run[week_runs[NEXT]]
        assert set(weekly) == set(DAG_STAGES), sorted(weekly)
        assert {r.run_type for r in weekly.values()} == {RunType.WEEKLY}
        for stage in ("generate", "ingest", "export"):
            assert weekly[stage].status is StageStatus.SUCCESS, (NEXT, stage)
        assert weekly["checks"].status in {StageStatus.SUCCESS, StageStatus.WARN}
        _assert_dbt_ok(weekly["dbt_build"], NEXT)

        for week, run_id in week_runs.items():
            results = {c.check_id: c for c in meta.get_check_results(con, run_id)}
            # Everything the generator injected was quarantined, and nothing else.
            assert results["DQ033"].status is CheckStatus.PASS, (week, results["DQ033"].message)
            assert results["DQ030"].status is CheckStatus.PASS, week
            assert results["DQ032"].status is CheckStatus.PASS, week

        assert {r.run_type for r in runs if r.iso_week_id != NEXT} == {RunType.BACKFILL}
        in_mart = {
            week
            for (week,) in con.execute(
                "SELECT DISTINCT iso_week_id FROM marts.mart_org_weekly"
            ).fetchall()
        }
        # Exactly the backfilled weeks and the weekly run. The first week also loads a
        # warm-up year that feeds the 12-month window but is never reported (#273), so
        # its late rows before FIRST do not show up as partial weeks.
        assert sorted(in_mart) == [*backfilled, NEXT]
    finally:
        con.close()
