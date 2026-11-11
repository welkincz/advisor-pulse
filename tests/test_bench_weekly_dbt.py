"""The weekly dbt benchmark fails 20% over its baseline, not on a slower runner (#304)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "bench_weekly_dbt", ROOT / "scripts/bench_weekly_dbt.py"
)
assert spec and spec.loader
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)


def _fake(models_s: float, calibration_s: float) -> Any:
    def measure(work: Path, weeks: tuple[str, str], trials: int) -> dict[str, Any]:
        return {"calibration_s": calibration_s, "ratio": round(models_s / calibration_s, 3)}

    return measure


@pytest.mark.parametrize(
    ("models_s", "calibration_s", "code"),
    [
        (4.0, 0.25, 0),  # the baseline itself
        (4.8, 0.25, 0),  # 20% slower: still within budget
        (5.0, 0.25, 1),  # 25% slower: over budget
        (10.0, 0.625, 0),  # a runner 2.5x slower in everything: the same ratio passes
    ],
)
def test_budget_is_twenty_percent_over_the_normalized_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    models_s: float,
    calibration_s: float,
    code: int,
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"ratio": 16.0}))
    monkeypatch.setattr(bench, "measure", _fake(models_s, calibration_s))
    assert bench.main(["--baseline", str(baseline)]) == code


def test_record_writes_the_baseline_and_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = tmp_path / "new" / "baseline.json"
    monkeypatch.setattr(bench, "measure", _fake(99.0, 0.25))
    assert bench.main(["--baseline", str(baseline), "--record"]) == 0
    assert json.loads(baseline.read_text())["ratio"] == 396.0


def test_committed_baseline_has_a_ratio() -> None:
    assert json.loads(bench.BASELINE.read_text())["ratio"] > 0
