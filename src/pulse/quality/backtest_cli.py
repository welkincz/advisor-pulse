"""Reproduce the flag backtest, tune on one seed and confirm on another (ADR 0006)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import duckdb

from pulse.generate.advisors import REPORT_START, assignment_ranges
from pulse.generate.cli import Sizes, build_world
from pulse.generate.truth import GroundTruth, ground_truth, write_ground_truth
from pulse.quality.backtest import (
    PREVIOUS,
    SHIPPED,
    Score,
    Thresholds,
    _connect,
    _node_weeks,
    _weeks,
    flags,
    mismatches,
    score,
)
from pulse.reference import org


def _seed(data_dir: Path) -> int:
    manifest = json.loads((data_dir / "defects.json").read_text(encoding="utf-8"))
    return int(manifest["seed"])


@dataclass
class Warehouse:
    """One built warehouse and its ground truth, ready to score."""

    data_dir: Path
    con: duckdb.DuckDBPyConnection
    truth: GroundTruth
    node_weeks: dict[str, int]

    def score(self, t: Thresholds = SHIPPED) -> list[Score]:
        return score(self.truth, flags(self.con, t), self.node_weeks)


def open_warehouse(data_dir: Path, sizes: Sizes | None = None) -> Warehouse:
    """Connect read-only, derive the ground truth from the seed and write it beside the data."""
    con = _connect(data_dir)
    first, last, last_week = _weeks(con)
    seed = _seed(data_dir)
    world = build_world(seed, sizes or Sizes(), last_week)
    truth = ground_truth(
        org(),
        assignment_ranges(world.roster),
        world.clients,
        world.portfolios,
        seed=seed,
        first=max(first, REPORT_START),
        last=last,
    )
    write_ground_truth(truth, data_dir)
    return Warehouse(data_dir, con, truth, _node_weeks(con))


# ── Tuning ──────────────────────────────────────────────────────────────────

Z_GRID = (2.0, 2.5, 3.0, 3.5, 4.0)
PRTF_Z_GRID = (1.5, 2.0, 2.5, 3.0)
PRTF_MOVE_GRID = (0.001, 0.002, 0.003, 0.005)
# A branch manager can act on about one unexplained flag a month across every measure, so
# the alerting rules together may raise at most 25 false alarms per 100 branch-weeks.
ALERT_BUDGET = 25.0
ALERT_RULES = ("ANOMALY", "PRTF_MOVE")


def _objective(scores: Sequence[Score]) -> tuple[float, ...] | None:
    """Most stories caught, then the shortest lags, then the fewest false alarms; None when
    the branch-level false alarms of the alerting rules exceed the budget."""
    alerting = [s for s in scores if s.rule in ALERT_RULES]
    branch_false = sum(s.false_per_100_node_weeks for s in alerting if s.level == "BRANCH")
    if branch_false > ALERT_BUDGET:
        return None
    detected = sum(s.detected for s in alerting)
    lags = [s.median_lag_weeks for s in alerting if s.median_lag_weeks is not None]
    false = sum(s.false_alarms for s in alerting)
    return (detected, -sum(lags), -false)


def tune(warehouse: Warehouse) -> Thresholds:
    """The grid point with the best objective on one seed. The two alerting rules flag
    different measures, so each is searched on its own and the best pair is combined."""
    anomaly = {z: warehouse.score(replace(SHIPPED, z=z)) for z in Z_GRID}
    prtf = {
        (pz, move): warehouse.score(replace(SHIPPED, prtf_z=pz, prtf_min_move=move))
        for pz in PRTF_Z_GRID
        for move in PRTF_MOVE_GRID
    }
    best: tuple[tuple[float, ...], Thresholds] | None = None
    for z, a_scores in anomaly.items():
        for (pz, move), p_scores in prtf.items():
            combined = [s for s in a_scores if s.rule == "ANOMALY"]
            combined += [s for s in p_scores if s.rule == "PRTF_MOVE"]
            value = _objective(combined)
            if value is not None and (best is None or value > best[0]):
                best = (value, replace(SHIPPED, z=z, prtf_z=pz, prtf_min_move=move))
    if best is None:
        raise ValueError("No grid point keeps false alarms within the alert budget.")
    return best[1]


# ── Report ──────────────────────────────────────────────────────────────────


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def table(scores: Sequence[Score]) -> str:
    def lag(value: float | None) -> str:
        return "–" if value is None else f"{value:g}"

    head = (
        "| Seed | Rule | Level | Stories | Recall | Median lag (wk) | Flags | Hits | Explained "
        "| False | of which calendar | Precision | False / 100 node-weeks |\n"
        "|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"
    )
    rows = [
        f"| {s.seed} | {s.rule} | {s.level} | {s.stories} | {_pct(s.recall)} | "
        f"{lag(s.median_lag_weeks)} | {s.flags} | {s.hits} | "
        f"{s.explained} | {s.false_alarms} | {s.calendar_false_alarms} | {_pct(s.precision)} | "
        f"{s.false_per_100_node_weeks} |"
        for s in scores
    ]
    return "\n".join([head, *rows])


WEB_ROWS = (("ANOMALY", "BRANCH"), ("ANOMALY", "DISTRICT"), ("PRTF_MOVE", "BRANCH"))


def web_module(before: Sequence[Score], shipped: Sequence[Score], seeds: Sequence[int]) -> str:
    """The /quality page's table: the held-out (last) seed, before and after tuning."""
    if len(seeds) < 2 or seeds[0] == seeds[-1]:
        raise ValueError("Tuning and held-out evidence require two distinct seeds.")
    held_out = seeds[-1]

    def pick(scores: Sequence[Score], rule: str, level: str) -> Score:
        return next(s for s in scores if (s.seed, s.rule, s.level) == (held_out, rule, level))

    rows = []
    for rule, level in WEB_ROWS:
        old, new = pick(before, rule, level), pick(shipped, rule, level)
        rows.append(
            {
                "rule": rule,
                "level": level,
                "stories": new.stories,
                "detected": new.detected,
                "recall": new.recall,
                "medianLagWeeks": new.median_lag_weeks,
                "precision": new.precision,
                "falsePer100": new.false_per_100_node_weeks,
                "falsePer100Before": old.false_per_100_node_weeks,
                "detectedBefore": old.detected,
            }
        )
    body = json.dumps({"tunedSeed": seeds[0], "heldOutSeed": held_out, "rows": rows}, indent=2)
    return (
        "// Written by `make backtest` (src/pulse/quality/backtest_cli.py); do not edit by hand.\n"
        "// The shipped flag rules scored against the generator's ground truth (ADR 0006).\n"
        f"export const FLAG_BACKTEST = {body} as const\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dirs", nargs="+", type=Path, help="Built data dirs; first tunes.")
    parser.add_argument("--tune", action="store_true", help="Search the grid on the first.")
    parser.add_argument("--json", type=Path, help="Write every score here as JSON.")
    parser.add_argument("--web", type=Path, help="Write the /quality page's TS module here.")
    parser.add_argument("--advisors", type=int, default=Sizes().advisors)
    parser.add_argument("--clients", type=int, default=Sizes().clients)
    args = parser.parse_args(argv)
    sizes = Sizes(advisors=args.advisors, clients=args.clients)

    warehouses = [open_warehouse(d, sizes) for d in args.data_dirs]
    for w in warehouses:
        bad = mismatches(w.con)
        if bad:
            print(
                f"{w.data_dir}: the re-run rules at the shipped thresholds disagree with "
                f"mart_weekly_report on {bad} rows; rebuild the mart or update SHIPPED."
            )
            return 1
    candidates = {"before": PREVIOUS, "shipped": SHIPPED}
    if args.tune:
        candidates["tuned on the first seed"] = tune(warehouses[0])
    seeds = [w.truth.seed for w in warehouses]
    out: dict[str, object] = {"seeds": seeds}
    for name, t in candidates.items():
        scores = [s for w in warehouses for s in w.score(t)]
        print(f"\n## {name}: {t}\n")
        print(table(scores))
        out[name] = {"thresholds": asdict(t), "scores": [asdict(s) for s in scores]}
    if args.web:
        before = [s for w in warehouses for s in w.score(PREVIOUS)]
        shipped = [s for w in warehouses for s in w.score(SHIPPED)]
        args.web.write_text(web_module(before, shipped, seeds), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
