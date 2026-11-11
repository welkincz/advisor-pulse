"""Which signal warns earliest that a branch's 12-month contacted rate will fall? (#302)

    uv run python scripts/leading_indicator.py TUNE_DATA_DIR HELD_OUT_DATA_DIR --json out.json

Each signal is known at week t. The target is the branch's rate falling by at least --fall
points by t+13. Thresholds are fitted on the first warehouse's weeks up to --split, then scored
without refitting on its later weeks and on the second warehouse, a seed the fit never saw.
The naive baseline is the rate's own fall over the 13 weeks before t. Read-only.

stale_9m and stale_9m_rise_13w ship as mart_org_weekly.stale_9m_share and stale_9m_rise_13w
(ADR 0009); tests/integration/test_stale_book.py keeps the two definitions in step.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from pulse.warehouse import WAREHOUSE_FILE

HORIZON = 13
BASELINE = "rate_fall_13w"
SIGNALS = (
    BASELINE,
    "stale_9m",
    "stale_9m_rise_13w",
    "median_days_since",
    "median_days_rise_13w",
    "top_decile_share",
    "top_decile_rise_13w",
    "unique_clients_fall_13w",
)

_PANEL = """
with reported as (
    select iso_week_id, row_number() over (order by iso_week_id) as week_index
    from (select distinct iso_week_id from marts.mart_org_weekly
          where level = 'BRANCH' and portfolio_contacted_rate_12m is not null)
),
book as (
    select
        c.iso_week_id, c.transit_branch_id as branch_id,
        avg(case when c.last_contact_date is null
                   or c.last_contact_date <= cast(c.week_end - interval 9 month as date)
            then 1.0 else 0.0 end) as stale_9m,
        median(date_diff('day', c.last_contact_date, c.week_end)) as median_days_since
    from intermediate.int_client_contact_12m as c
    inner join reported using (iso_week_id)
    group by 1, 2
),
contacts as (
    select client_id, activity_date
    from intermediate.int_activity_enriched
    where status = 'COMPLETED' and client_id is not null
),
counted as (
    select c.iso_week_id, c.transit_branch_id as branch_id, count(a.client_id) as touches
    from intermediate.int_client_contact_12m as c
    inner join reported using (iso_week_id)
    left join contacts as a
        on a.client_id = c.client_id
        and a.activity_date > cast(c.week_end - interval 12 month as date)
        and a.activity_date <= c.week_end
    group by c.iso_week_id, c.transit_branch_id, c.client_id
),
ranked as (
    select *,
        row_number() over (partition by iso_week_id, branch_id order by touches desc) as place,
        count(*) over (partition by iso_week_id, branch_id) as clients
    from counted
),
concentration as (
    select iso_week_id, branch_id,
        sum(touches) filter (where place <= greatest(1, clients / 10))
            / nullif(sum(touches), 0) as top_decile_share
    from ranked
    group by 1, 2
),
rates as (
    select o.node_id as branch_id, o.iso_week_id, r.week_index,
        o.portfolio_contacted_rate_12m as rate,
        cast(o.unique_clients_contacted as double) as unique_clients
    from marts.mart_org_weekly as o
    inner join reported as r using (iso_week_id)
    where o.level = 'BRANCH'
),
joined as (
    select rates.*, book.stale_9m, book.median_days_since, concentration.top_decile_share,
        avg(unique_clients) over recent as unique_recent,
        avg(unique_clients) over earlier as unique_earlier
    from rates
    inner join book using (iso_week_id, branch_id)
    inner join concentration using (iso_week_id, branch_id)
    window
        recent as (partition by branch_id order by week_index rows 12 preceding),
        earlier as (
            partition by branch_id order by week_index
            rows between 25 preceding and 13 preceding
        )
)
select
    now.branch_id, now.iso_week_id, now.week_index,
    now.rate,
    ahead.rate as rate_ahead,
    past.rate - now.rate as rate_fall_13w,
    now.stale_9m,
    now.stale_9m - past.stale_9m as stale_9m_rise_13w,
    now.median_days_since,
    now.median_days_since - past.median_days_since as median_days_rise_13w,
    now.top_decile_share,
    now.top_decile_share - past.top_decile_share as top_decile_rise_13w,
    (now.unique_earlier - now.unique_recent) / nullif(now.unique_earlier, 0)
        as unique_clients_fall_13w
from joined as now
inner join joined as past
    on past.branch_id = now.branch_id and past.week_index = now.week_index - 13
inner join joined as ahead
    on ahead.branch_id = now.branch_id and ahead.week_index = now.week_index + 13
order by now.iso_week_id, now.branch_id
"""


@dataclass(frozen=True)
class Row:
    branch: str
    week: str
    index: int
    fell: bool
    values: dict[str, float]


@dataclass(frozen=True)
class Scored:
    signal: str
    sample: str
    threshold: float
    rows: int
    positives: int
    flags: int
    precision: float | None
    recall: float | None
    f1: float
    median_lead_weeks: float | None
    auc: float | None


def load_panel(data_dir: Path, fall_points: float) -> list[Row]:
    con = duckdb.connect(str(data_dir / WAREHOUSE_FILE), read_only=True)
    cursor = con.execute(_PANEL)
    names = [d[0] for d in cursor.description]
    rows = []
    for raw in cursor.fetchall():
        record = dict(zip(names, raw, strict=True))
        if any(record[s] is None for s in SIGNALS):
            continue
        rows.append(
            Row(
                branch=str(record["branch_id"]),
                week=str(record["iso_week_id"]),
                index=int(record["week_index"]),
                fell=record["rate"] - record["rate_ahead"] >= fall_points / 100,
                values={s: float(record[s]) for s in SIGNALS},
            )
        )
    con.close()
    return rows


def auc(signal: str, rows: Sequence[Row]) -> float | None:
    """The chance a falling branch-week scores above one that does not; ties count half."""
    ordered = sorted(rows, key=lambda r: r.values[signal])
    positives = sum(r.fell for r in ordered)
    negatives = len(ordered) - positives
    if not positives or not negatives:
        return None
    rank_sum = 0.0
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and (ordered[j + 1].values[signal] == ordered[i].values[signal]):
            j += 1
        average = (i + j) / 2 + 1
        rank_sum += average * sum(r.fell for r in ordered[i : j + 1])
        i = j + 1
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def _confusion(signal: str, threshold: float, rows: Sequence[Row]) -> tuple[int, int, int]:
    hits = flags = positives = 0
    for row in rows:
        flagged = row.values[signal] >= threshold
        flags += flagged
        positives += row.fell
        hits += flagged and row.fell
    return hits, flags, positives


def _f1(hits: int, flags: int, positives: int) -> float:
    return 2 * hits / (flags + positives) if flags + positives else 0.0


def fit_threshold(signal: str, rows: Sequence[Row], steps: int = 200) -> float:
    """The cut with the best F1 on the tuning rows, searched over the signal's quantiles."""
    values = sorted(r.values[signal] for r in rows)
    candidates = sorted({values[(i * (len(values) - 1)) // steps] for i in range(steps + 1)})
    return max(candidates, key=lambda cut: (_f1(*_confusion(signal, cut, rows)), -cut))


def median_lead(
    signal: str, threshold: float, rows: Sequence[Row], baseline_cut: float
) -> float | None:
    """Per branch, weeks from the signal's first correct flag until the rate's own trend flags
    that branch too, at most the 13-week horizon: how far ahead of reading the rate it was."""
    leads = []
    for branch in {r.branch for r in rows}:
        history = sorted((r for r in rows if r.branch == branch), key=lambda r: r.index)
        flagged = next((r for r in history if r.fell and r.values[signal] >= threshold), None)
        if flagged is None:
            continue
        seen = next(
            (r for r in history if r.index >= flagged.index and r.values[BASELINE] >= baseline_cut),
            None,
        )
        leads.append(HORIZON if seen is None else min(HORIZON, seen.index - flagged.index))
    return statistics.median(leads) if leads else None


def score(
    signal: str, threshold: float, sample: str, rows: Sequence[Row], baseline_cut: float
) -> Scored:
    hits, flags, positives = _confusion(signal, threshold, rows)
    area = auc(signal, rows)
    return Scored(
        signal=signal,
        sample=sample,
        threshold=round(threshold, 5),
        rows=len(rows),
        positives=positives,
        flags=flags,
        precision=round(hits / flags, 3) if flags else None,
        recall=round(hits / positives, 3) if positives else None,
        f1=round(_f1(hits, flags, positives), 3),
        median_lead_weeks=median_lead(signal, threshold, rows, baseline_cut),
        auc=round(area, 3) if area is not None else None,
    )


def compare(tune: Sequence[Row], later: Sequence[Row], held_out: Sequence[Row]) -> list[Scored]:
    results = []
    baseline_cut = fit_threshold(BASELINE, tune)
    for signal in SIGNALS:
        cut = fit_threshold(signal, tune)
        for sample, rows in (("tune", tune), ("later weeks", later), ("held-out seed", held_out)):
            results.append(score(signal, cut, sample, rows, baseline_cut))
    return results


def _text(value: float | None) -> str:
    return "–" if value is None else f"{value:g}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tune_dir", type=Path)
    parser.add_argument("held_out_dir", type=Path)
    parser.add_argument("--fall", type=float, default=0.5, help="Points the rate must fall.")
    parser.add_argument("--split", default="2026-W05", help="Last week used to fit thresholds.")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    first = load_panel(args.tune_dir, args.fall)
    tune = [r for r in first if r.week <= args.split]
    later = [r for r in first if r.week > args.split]
    results = compare(tune, later, load_panel(args.held_out_dir, args.fall))
    print(
        "| Signal | Sample | Cut | Branch-weeks | Falling | Flags | Precision | Recall | F1 "
        "| Median lead (wk) | AUC |\n|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"
    )
    for r in results:
        print(
            f"| {r.signal} | {r.sample} | {r.threshold:g} | {r.rows} | {r.positives} | {r.flags} | "
            f"{_text(r.precision)} | {_text(r.recall)} | {r.f1:g} | "
            f"{_text(r.median_lead_weeks)} | {_text(r.auc)} |"
        )
    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in results], indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
