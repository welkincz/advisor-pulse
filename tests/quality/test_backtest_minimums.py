"""The shipped flag rules keep catching the generator's stories (ADR 0006).

Builds a default-scale warehouse over a shorter window that still holds both stories
(2026-W14 to 2026-W42, plus the 52-week warm-up the first week loads), then scores the
flags against the ground truth. The minimums sit a little under what the shipped
thresholds reach here, so a later change to the rules cannot silently make detection
worse. About 35 minutes on a laptop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pulse.contracts.enums import RunType
from pulse.generate.cli import DEFAULT_SEED, Sizes, generate_weeks, week_range
from pulse.quality.backtest import Score, mismatches
from pulse.quality.backtest_cli import open_warehouse
from pulse.runner.command import run_week

pytestmark = [pytest.mark.integration, pytest.mark.slow]

FIRST, LAST = "2026-W14", "2026-W42"

# (rule, level): minimum recall, maximum median lag in weeks, maximum false alarms per 100
# node-weeks.
MINIMUMS = {
    ("ANOMALY", "DISTRICT"): (1.0, 2, 25.0),
    ("ANOMALY", "BRANCH"): (0.9, 3, 25.0),
    ("PRTF_MOVE", "BRANCH"): (0.6, 40, 10.0),
}


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 19, 4, tzinfo=UTC)

    def sleep(self, seconds: float) -> None:
        pass


def test_shipped_flags_meet_the_regression_minimums(tmp_path: Path) -> None:
    generate_weeks(tmp_path, week_range(FIRST, LAST), seed=DEFAULT_SEED, sizes=Sizes())
    run_week(LAST, data_dir=tmp_path, run_type=RunType.BACKFILL, clock=Clock(), echo=print)
    warehouse = open_warehouse(tmp_path, Sizes())
    assert mismatches(warehouse.con) == 0
    scores: dict[tuple[str, str], Score] = {(s.rule, s.level): s for s in warehouse.score()}
    for key, (recall, lag, false_rate) in MINIMUMS.items():
        s = scores[key]
        print(key, s)
        assert s.recall is not None and s.recall >= recall, key
        assert s.median_lag_weeks is not None and s.median_lag_weeks <= lag, key
        assert s.false_per_100_node_weeks <= false_rate, key
