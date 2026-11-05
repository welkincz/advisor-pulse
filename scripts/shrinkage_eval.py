"""Does empirical-Bayes shrinkage rank portfolios closer to the generator's truth? (#301)

    uv run python scripts/shrinkage_eval.py DATA_DIR [DATA_DIR ...] --json out.json

The generator knows how strongly each advisor concentrates contact on a few clients, which
sets how much of a book hears from them. Each built warehouse is scored at advisor and branch
level, before and after a beta-binomial shrink fitted by the method of moments. Read-only.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import duckdb

from pulse.generate.activity import _concentration
from pulse.warehouse import WAREHOUSE_FILE

WILSON_Z = 1.96
BOTTOM_SHARE = 0.1


def wilson(contacted: int, clients: int, z: float = WILSON_Z) -> tuple[float, float]:
    """The Wilson score interval for a rate."""
    if clients <= 0:
        raise ValueError("A Wilson interval needs at least one client.")
    rate = contacted / clients
    denominator = 1 + z * z / clients
    centre = (rate + z * z / (2 * clients)) / denominator
    spread = z * math.sqrt(rate * (1 - rate) / clients + z * z / (4 * clients**2)) / denominator
    return max(0.0, centre - spread), min(1.0, centre + spread)


def fit_prior(books: Sequence[tuple[int, int]]) -> tuple[float, float]:
    """(mean, kappa) of a beta prior by the method of moments; kappa is its strength in clients."""
    usable = [(x, n) for x, n in books if n > 0]
    total = sum(n for _, n in usable)
    mean = sum(x for x, _ in usable) / total
    between = sum(n * (x / n - mean) ** 2 for x, n in usable) / total
    sampling = sum(mean * (1 - mean) for _ in usable) / total
    excess = between - sampling
    if excess <= 0:
        return mean, math.inf
    return mean, max(mean * (1 - mean) / excess - 1, 0.0)


def shrink(contacted: int, clients: int, mean: float, kappa: float) -> float:
    if math.isinf(kappa):
        return mean
    return (contacted + mean * kappa) / (clients + kappa)


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    ra, rb = _ranks(a), _ranks(b)
    mean_a, mean_b = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(ra, rb, strict=True))
    var_a = sum((x - mean_a) ** 2 for x in ra)
    var_b = sum((y - mean_b) ** 2 for y in rb)
    return cov / math.sqrt(var_a * var_b) if var_a and var_b else 0.0


def bottom_overlap(estimate: Sequence[float], truth: Sequence[float]) -> float:
    """Share of the truly lowest decile that the estimate also puts in its lowest decile."""
    size = max(1, round(len(truth) * BOTTOM_SHARE))
    worst = set(sorted(range(len(truth)), key=lambda i: (truth[i], i))[:size])
    found = set(sorted(range(len(estimate)), key=lambda i: (estimate[i], i))[:size])
    return len(worst & found) / size


@dataclass(frozen=True)
class Result:
    seed: int
    week: str
    level: str
    nodes: int
    median_clients: float
    kappa: float
    moved_points_median: float
    spearman_raw: float
    spearman_shrunk: float
    bottom_raw: float
    bottom_shrunk: float
    mean_wilson_half_width: float


def score_level(seed: int, week: str, level: str, rows: Sequence[tuple[int, int, float]]) -> Result:
    """``rows`` are (contacted, clients, true expected rate proxy): higher is better."""
    books = [(x, n) for x, n, _ in rows]
    truth = [t for _, _, t in rows]
    mean, kappa = fit_prior(books)
    raw = [x / n for x, n in books]
    shrunk = [shrink(x, n, mean, kappa) for x, n in books]
    moved = sorted(abs(a - b) * 100 for a, b in zip(raw, shrunk, strict=True))
    clients = sorted(n for _, n in books)
    widths = [(hi - lo) / 2 for lo, hi in (wilson(x, n) for x, n in books)]
    return Result(
        seed=seed,
        week=week,
        level=level,
        nodes=len(rows),
        median_clients=clients[len(clients) // 2],
        kappa=round(kappa, 1) if not math.isinf(kappa) else -1.0,
        moved_points_median=round(moved[len(moved) // 2], 3),
        spearman_raw=round(spearman(raw, truth), 4),
        spearman_shrunk=round(spearman(shrunk, truth), 4),
        bottom_raw=round(bottom_overlap(raw, truth), 3),
        bottom_shrunk=round(bottom_overlap(shrunk, truth), 3),
        mean_wilson_half_width=round(100 * sum(widths) / len(widths), 2),
    )


def _advisor_rows(
    con: duckdb.DuckDBPyConnection, seed: int, week: str, day: date
) -> tuple[list[tuple[int, int, float]], list[tuple[int, int, float]]]:
    found = con.execute(
        "select advisor_id, branch_id, portfolio_contacted_12m, portfolio_clients "
        "from marts.mart_advisor_weekly where iso_week_id = ? and portfolio_clients > 0 "
        "order by advisor_id, branch_id",
        [week],
    ).fetchall()
    advisors = []
    branches: dict[str, list[tuple[int, int, float]]] = {}
    for advisor, branch, contacted, clients in found:
        truth = -_concentration(seed, advisor, day)
        advisors.append((int(contacted), int(clients), truth))
        branches.setdefault(branch, []).append((int(contacted), int(clients), truth))
    branch_rows = [
        (
            sum(x for x, _, _ in books),
            sum(n for _, n, _ in books),
            sum(n * t for _, n, t in books) / sum(n for _, n, _ in books),
        )
        for _, books in sorted(branches.items())
    ]
    return advisors, branch_rows


def evaluate(data_dir: Path, weeks: Sequence[str]) -> list[Result]:
    seed = int(json.loads((data_dir / "defects.json").read_text(encoding="utf-8"))["seed"])
    con = duckdb.connect(str(data_dir / WAREHOUSE_FILE), read_only=True)
    out = []
    for week in weeks:
        day = date.fromisoformat(f"{week}-7")
        advisors, branches = _advisor_rows(con, seed, week, day)
        out += [
            score_level(seed, week, "ADVISOR", advisors),
            score_level(seed, week, "BRANCH", branches),
        ]
    con.close()
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dirs", nargs="+", type=Path)
    parser.add_argument("--weeks", nargs="+", default=["2025-W52", "2026-W26", "2026-W42"])
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    results = [r for d in args.data_dirs for r in evaluate(d, args.weeks)]
    print(
        "| Seed | Week | Level | Nodes | Median clients | Kappa | Median move (pt) | Wilson ± (pt) "
        "| Spearman raw | Spearman shrunk | Bottom decile raw | Bottom decile shrunk |"
    )
    print("|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in results:
        print(
            f"| {r.seed} | {r.week} | {r.level} | {r.nodes} | {r.median_clients:g} | {r.kappa:g} | "
            f"{r.moved_points_median:g} | {r.mean_wilson_half_width:g} | {r.spearman_raw:.4f} | "
            f"{r.spearman_shrunk:.4f} | {r.bottom_raw:.0%} | {r.bottom_shrunk:.0%} |"
        )
    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in results], indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
