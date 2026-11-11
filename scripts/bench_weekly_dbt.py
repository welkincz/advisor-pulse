"""Weekly dbt benchmark on a scaled synthetic world, with a time budget (#304).

Builds a small world (default 20% of the generator's scale: the warm-up year plus
``--weeks`` reported weeks), runs the full ``dbt build`` once, then loads one more week and
times the weekly ``dbt build`` the runner would run, best of ``--trials`` from the same
starting state. Every phase calls the runner's own stage functions. The budgeted figure is
the summed time of the build's models (see ``_dbt``).

Runners differ in speed (#335 found a 49% gap from the machine alone), so the budget is
not in seconds. The script also times a fixed DuckDB workload on the same machine and
compares ``weekly model seconds / calibration seconds`` with the committed baseline: more
than 20% above it fails.

    uv run python scripts/bench_weekly_dbt.py                 # measure and check
    uv run python scripts/bench_weekly_dbt.py --record        # measure and rewrite the baseline
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from pulse.contracts.enums import RunType, StageStatus
from pulse.generate.cli import Sizes, week_range, week_start
from pulse.generate.stage import generate
from pulse.ingest.stage import ingest
from pulse.runner.stage import StageContext, StageResult
from pulse.runner.stages import DBT_TARGET_DIR, dbt_build
from pulse.warehouse import WAREHOUSE_FILE

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "benchmark" / "weekly_dbt_baseline.json"
SIZES = Sizes(advisors=360, clients=60_000)
FIRST, LAST = "2026-W33", "2026-W40"
NEXT = "2026-W41"
TOLERANCE = 1.20


class _Clock:
    """Monday 04:00 UTC after the week being run, as the weekly schedule has it."""

    def __init__(self, week: str) -> None:
        self.at = datetime.combine(week_start(week) + timedelta(days=7), datetime.min.time(), UTC)
        self.at += timedelta(hours=4)

    def now(self) -> datetime:
        return self.at

    def sleep(self, seconds: float) -> None:
        pass


def _ctx(data_dir: Path, week: str) -> StageContext:
    return StageContext(f"bench-{week}", RunType.MANUAL, week, data_dir, _Clock(week))


def _ok(result: StageResult, what: str) -> None:
    if result.status is StageStatus.FAILED:
        raise SystemExit(f"{what} failed: {result.message}")


def _load(data_dir: Path, week: str) -> None:
    ctx = _ctx(data_dir, week)
    _ok(generate(ctx, SIZES), f"generate {week}")
    _ok(ingest(ctx), f"ingest {week}")


def _dbt(data_dir: Path, week: str) -> tuple[float, dict[str, float]]:
    """dbt's elapsed time for the build, and the time of each model.

    Parsing is outside both. The models' sum is the budgeted figure: it is the work that
    grows with the data, while the elapsed time also carries about 500 tests and nodes
    whose cost is fixed per node.
    """
    _ok(dbt_build(_ctx(data_dir, week)), f"dbt build {week}")
    results = json.loads((data_dir / DBT_TARGET_DIR / "run_results.json").read_text())
    models = {
        r["unique_id"].split(".")[-1]: float(r["execution_time"])
        for r in results["results"]
        if r["unique_id"].startswith("model.")
    }
    return float(results["elapsed_time"]), models


def calibrate(trials: int = 5) -> float:
    """Seconds for a fixed DuckDB join and aggregation: this machine's speed, best of N."""
    con = duckdb.connect()
    con.execute("set threads = 4")
    best = float("inf")
    for _ in range(trials):
        start = time.perf_counter()
        con.execute(
            "with a as (select range as id, hash(range) % 50000 as k from range(6000000)), "
            "b as (select range as k, hash(range) % 97 as g from range(50000)) "
            "select g, count(distinct id % 400000), sum(id) from a join b using (k) group by g"
        ).fetchall()
        best = min(best, time.perf_counter() - start)
    con.close()
    return best


def measure(work: Path, weeks: tuple[str, str], trials: int) -> dict[str, Any]:
    data = work / "data"
    data.mkdir(parents=True)
    for week in week_range(*weeks):
        _load(data, week)
    full_elapsed, full_models = _dbt(data, weeks[1])
    _load(data, NEXT)
    snapshot = work / "snapshot.duckdb"
    shutil.copyfile(data / WAREHOUSE_FILE, snapshot)
    weekly = []
    for _ in range(trials):
        shutil.copyfile(snapshot, data / WAREHOUSE_FILE)
        weekly.append(_dbt(data, NEXT))
    calibration = calibrate()
    _, fastest = min(weekly, key=lambda trial: sum(trial[1].values()))
    best = sum(fastest.values())
    return {
        "sizes": {"advisors": SIZES.advisors, "clients": SIZES.clients},
        "weeks": f"{weeks[0]}..{weeks[1]} then {NEXT}",
        "full_build": {
            "elapsed_s": round(full_elapsed, 2),
            "models_s": round(sum(full_models.values()), 2),
        },
        "weekly_build": [
            {"elapsed_s": round(elapsed, 2), "models_s": round(sum(models.values()), 2)}
            for elapsed, models in weekly
        ],
        "slowest_weekly_models_s": {
            name: round(seconds, 2)
            for name, seconds in sorted(fastest.items(), key=lambda kv: -kv[1])[:8]
        },
        "calibration_s": round(calibration, 3),
        "ratio": round(best / calibration, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--record", action="store_true", help="Write the result as the baseline.")
    parser.add_argument("--out", type=Path, help="Also write the result here as JSON.")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="pulse-bench-") as work:
        result = measure(Path(work), (FIRST, LAST), args.trials)
    print(json.dumps(result, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n")
    if args.record:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(result, indent=2) + "\n")
        print(f"Baseline written to {args.baseline}.")
        return 0

    baseline = json.loads(args.baseline.read_text())
    budget = baseline["ratio"] * TOLERANCE
    verdict = "within" if result["ratio"] <= budget else "OVER"
    print(
        f"Weekly dbt models {result['ratio'] * result['calibration_s']:.2f} s"
        f" = {result['ratio']:.3f} x calibration; "
        f"baseline {baseline['ratio']:.3f}, budget {budget:.3f} (+{TOLERANCE - 1:.0%}): {verdict}."
    )
    return 0 if result["ratio"] <= budget else 1


if __name__ == "__main__":
    sys.exit(main())
