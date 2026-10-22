"""End to end: an 8-week backfill from nothing, then one weekly run, on the real DAG.

The generator runs at the small sizes tests/conftest.py sets, so this takes about a
minute. docs/baseline.md records the same run at default scale over 104 weeks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pulse.contracts.enums import CheckStatus, RunType, StageStatus
from pulse.generate.cli import week_range
from pulse.ingest import meta
from pulse.runner.backfill import backfill_range
from pulse.runner.command import run_week
from pulse.warehouse import WAREHOUSE_FILE, connect

pytestmark = [pytest.mark.integration, pytest.mark.slow]

FIRST, LAST, NEXT = "2026-W33", "2026-W40", "2026-W41"


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 12, 4, tzinfo=UTC)

    def sleep(self, seconds: float) -> None:
        pass


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
        weeks = [*week_range(FIRST, LAST), NEXT]
        finals = {(r.iso_week_id, r.stage): r for r in runs if r.status is not StageStatus.RUNNING}
        for week in weeks:
            for stage in ("generate", "ingest"):
                assert finals[(week, stage)].status is StageStatus.SUCCESS, (week, stage)
            # At test size a branch has one or two advisors, so a handover often goes to
            # someone at another branch and DQ025 warns. That is the only warning allowed.
            dbt = finals[(week, "dbt_build")]
            if dbt.status is not StageStatus.SUCCESS:
                assert dbt.status is StageStatus.WARN, (week, dbt.message)
                assert "1 warned: dq025_portfolio_holder_at_another_branch" in (
                    dbt.message or ""
                ), (
                    week,
                    dbt.message,
                )
            assert finals[(week, "checks")].status in {StageStatus.SUCCESS, StageStatus.WARN}
            if week not in (LAST, NEXT):
                # Template narration is the plan for backfilled history, not a warning. The
                # last backfill week and the weekly run try the model and warn without one.
                assert finals[(week, "narrate")].status is StageStatus.SUCCESS, week

            run_id = finals[(week, "checks")].run_id
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
        # Plus the 3 partial weeks before FIRST that its late rows (1–3 weeks) land in.
        assert sorted(in_mart) == [*week_range("2026-W30", "2026-W32"), *weeks]
    finally:
        con.close()
