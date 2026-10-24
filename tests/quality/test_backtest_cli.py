"""Held-out evidence and the operational false-alarm budget cannot be bypassed."""

from datetime import date

import pytest

from pulse.generate.truth import GroundTruth
from pulse.quality import backtest_cli
from pulse.quality.backtest import _Flag, score


def test_held_out_table_rejects_reusing_the_tuning_seed() -> None:
    with pytest.raises(ValueError, match="distinct"):
        backtest_cli.web_module([], [], [7, 7])


def test_tuning_rejects_a_grid_point_over_the_branch_alert_budget() -> None:
    def scores(n: int):
        found = [
            _Flag("2026-W09", date(2026, 2, 23), "BRANCH", str(i), "CALLS_OUT", "ANOMALY", "UP")
            for i in range(n)
        ]
        return score(GroundTruth(7, (), ()), found, {"BRANCH": 100})

    assert backtest_cli._objective(scores(20)) is not None
    assert backtest_cli._objective(scores(26)) is None
