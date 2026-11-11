"""The leading-indicator scoring, on small panels with known answers (#302)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "leading_indicator.py"
    spec = importlib.util.spec_from_file_location("leading_indicator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["leading_indicator"] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


li = _load()


def row(value: float, fell: bool, branch: str = "BR-1", index: int = 1, trend: float = 0.0):
    return li.Row(
        branch=branch,
        week=f"2026-W{index:02d}",
        index=index,
        fell=fell,
        values={"stale_9m": value, li.BASELINE: trend},
    )


def test_auc_is_one_half_and_one_at_the_known_cases() -> None:
    assert li.auc("stale_9m", [row(1, True), row(2, False), row(1, False), row(2, True)]) == 0.5
    assert li.auc("stale_9m", [row(1, False), row(2, False), row(3, True)]) == 1.0
    assert li.auc("stale_9m", [row(1, True)]) is None


def test_the_threshold_separates_a_clean_signal() -> None:
    rows = [row(v / 10, v >= 7) for v in range(10)]
    assert li.fit_threshold("stale_9m", rows) == pytest.approx(0.7)


def test_scoring_counts_precision_and_recall() -> None:
    rows = [row(1, True), row(1, False), row(0, True), row(0, False)]
    scored = li.score("stale_9m", 1.0, "held-out seed", rows, baseline_cut=9.0)
    assert (scored.flags, scored.positives, scored.precision, scored.recall) == (2, 2, 0.5, 0.5)
    assert scored.f1 == 0.5


def test_a_cut_fitted_on_tuning_rows_is_not_refitted_on_held_out_rows() -> None:
    tune = [row(v / 10, v >= 7) for v in range(10)]
    held_out = [row(v / 10, v >= 2) for v in range(10)]
    signals = li.SIGNALS
    li.SIGNALS = ("stale_9m",)
    try:
        results = li.compare(
            [li.Row(r.branch, r.week, r.index, r.fell, {**r.values}) for r in tune],
            held_out,
            held_out,
        )
    finally:
        li.SIGNALS = signals
    assert all(r.threshold == pytest.approx(0.7) for r in results)
    assert next(r for r in results if r.sample == "held-out seed").recall == pytest.approx(3 / 8)


def test_lead_is_the_weeks_before_the_rate_trend_flags() -> None:
    rows = [
        row(1, True, index=10),
        row(1, True, index=11),
        row(1, True, index=14, trend=5.0),
    ]
    assert li.median_lead("stale_9m", 1.0, rows, baseline_cut=5.0) == 4


def test_lead_is_the_horizon_when_the_trend_never_flags_and_none_without_a_hit() -> None:
    assert li.median_lead("stale_9m", 1.0, [row(1, True)], baseline_cut=5.0) == li.HORIZON
    assert li.median_lead("stale_9m", 1.0, [row(0, True)], baseline_cut=5.0) is None
