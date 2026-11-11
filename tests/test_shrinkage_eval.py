"""The shrinkage evaluation's statistics, against hand-checked values (#301)."""

from __future__ import annotations

import importlib.util
import math
import random
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "shrinkage_eval.py"
    spec = importlib.util.spec_from_file_location("shrinkage_eval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["shrinkage_eval"] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


evaluation = _load()


def test_wilson_matches_a_published_value_and_holds_the_rate() -> None:
    low, high = evaluation.wilson(90, 100)
    assert low == pytest.approx(0.8256, abs=1e-3)
    assert high == pytest.approx(0.9448, abs=1e-3)
    assert low <= 0.9 <= high


@pytest.mark.parametrize(("contacted", "clients"), [(0, 40), (40, 40), (1, 1)])
def test_wilson_stays_a_rate_at_the_edges(contacted: int, clients: int) -> None:
    low, high = evaluation.wilson(contacted, clients)
    assert 0 <= low <= contacted / clients <= high <= 1


def test_wilson_refuses_an_empty_book() -> None:
    with pytest.raises(ValueError, match="at least one client"):
        evaluation.wilson(0, 0)


def test_a_small_book_moves_further_than_a_large_one() -> None:
    mean, kappa = 0.85, 100.0
    small = abs(evaluation.shrink(36, 40, mean, kappa) - 36 / 40)
    large = abs(evaluation.shrink(810, 900, mean, kappa) - 810 / 900)
    assert small > 3 * large


def test_books_with_no_real_spread_shrink_fully_to_the_mean() -> None:
    mean, kappa = evaluation.fit_prior([(85, 100)] * 20)
    assert mean == pytest.approx(0.85)
    assert math.isinf(kappa)
    assert evaluation.shrink(90, 100, mean, kappa) == pytest.approx(mean)


def test_the_prior_recovers_a_known_spread() -> None:
    rng = random.Random(7)
    books = []
    for _ in range(2000):
        rate = rng.betavariate(40, 10)  # mean 0.8, kappa 50
        books.append((sum(rng.random() < rate for _ in range(60)), 60))
    mean, kappa = evaluation.fit_prior(books)
    assert mean == pytest.approx(0.8, abs=0.01)
    assert 35 < kappa < 70


def test_shrinkage_helps_when_books_are_small_and_uneven() -> None:
    """The evaluation can see a gain when one exists, so a flat result is a real finding."""
    rng = random.Random(11)
    rows = []
    for i in range(600):
        rate = rng.betavariate(40, 10)
        clients = 8 if i % 2 else 400
        rows.append((sum(rng.random() < rate for _ in range(clients)), clients, rate))
    result = evaluation.score_level(1, "2026-W42", "ADVISOR", rows)
    assert result.spearman_shrunk > result.spearman_raw + 0.02


def test_spearman_and_bottom_overlap() -> None:
    assert evaluation.spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1)
    assert evaluation.spearman([1, 2, 3], [30, 20, 10]) == pytest.approx(-1)
    assert evaluation.spearman([1, 1, 1], [1, 2, 3]) == 0
    truth = list(range(20))
    assert evaluation.bottom_overlap(truth, truth) == 1
    assert evaluation.bottom_overlap(truth[::-1], truth) == 0
