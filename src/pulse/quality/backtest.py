"""Score the weekly report's flags against the generator's ground truth (ADR 0006).

The flag rules of ``mart_weekly_report`` are re-run in DuckDB over the built warehouse with
the thresholds as parameters. At the shipped thresholds the result must equal the mart's
``flag`` column row for row, so the backtest measures the rules the site shows, and the
same SQL can try other thresholds without rebuilding dbt.

Three rules, each at every level of the report:

- ``ANOMALY``: a measure more than ``z`` standard deviations from its 13 weeks before
  (every KPI except the rolling 12-month rate);
- ``PRTF_MOVE``: for ``PRTF_CONTACT_12M``, a weekly move more than ``prtf_z`` standard
  deviations from the 13 moves before and at least ``prtf_min_move``;
- ``DOWN`` / ``UP``: separate week-on-week labels when a measure moved ``wow_pct`` or more.

A flag is a **hit** when it points the way of a scored story at its node, on a measure the
story moves directly, inside the story's window. A direct match to a smaller story is
**explained**, also a precision positive. Indirect overlaps are not proof of a match and
count as false alarms. Precision is direct matches over ALL flags, recall is the share
of scored stories with at least one hit, and lag runs from a story's first changed week.
Calendar flags remain false alarms. Operational KPIs are included, but without injected
rate-change stories their recall is unassessed; their alerts count as unmatched.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from pulse.generate.truth import LEVELS, GroundTruth, Story
from pulse.warehouse import WAREHOUSE_FILE

RULES = ("ANOMALY", "PRTF_MOVE", "DOWN", "UP")


@dataclass(frozen=True)
class Thresholds:
    """The flag rule's knobs; the defaults are the shipped ones (PLAN.md §7)."""

    z: float = 3.0
    min_baseline_weeks: int = 8
    prtf_z: float = 2.0
    prtf_min_move: float = 0.002
    wow_pct: float = 0.01


SHIPPED = Thresholds()
PROPOSED = Thresholds(z=3.0, prtf_min_move=0.002)
# The thresholds before the backtest tuned them (ADR 0006).
PREVIOUS = Thresholds(z=2.0, prtf_min_move=0.005)


@dataclass(frozen=True)
class Score:
    seed: int
    rule: str
    level: str
    stories: int
    detected: int
    recall: float | None
    median_lag_weeks: float | None
    flags: int
    hits: int
    explained: int
    false_alarms: int
    calendar_false_alarms: int
    precision: float | None
    node_weeks: int
    false_per_100_node_weeks: float


# The mart's windows, recomputed once per warehouse: the 13 weeks before each week, of the
# values and of the week-on-week moves.
_PREPARE = """
create or replace temp table backtest_report as
with weeks as (
    select iso_week_id, min(week_start) as week_start from marts.dim_date group by 1
),
report as (
    select r.*, weeks.week_start
    from marts.mart_weekly_report as r
    inner join weeks using (iso_week_id)
),
values_before as (
    select
        *,
        avg(value) over before_13w as baseline_avg,
        stddev_samp(value) over before_13w as baseline_sd,
        count(value) over before_13w as baseline_weeks,
        avg(wow_delta) over before_13w as move_avg,
        stddev_samp(wow_delta) over before_13w as move_sd,
        count(wow_delta) over before_13w as move_weeks
    from report
    window before_13w as (
        partition by level, node_id, kpi_code
        order by week_start
        range between interval 91 day preceding and interval 7 day preceding
    )
)
select * from values_before
"""

# The mart's CASE with parameters ($z, $min_weeks, $prtf_z, $prtf_move, $wow), plus each
# flag's rule and the direction it points.
_FLAGS = """
select
    iso_week_id, week_start, level, node_id, kpi_code, flag as mart_flag,
    case
        when value is not null and baseline_weeks >= $min_weeks and baseline_sd > 0
            and abs(value - baseline_avg) / baseline_sd > $z
            and kpi_code <> 'PRTF_CONTACT_12M'
            then 'ANOMALY'
        when kpi_code = 'PRTF_CONTACT_12M' and move_weeks >= $min_weeks and move_sd > 0
            and abs(wow_delta - move_avg) / move_sd > $prtf_z
            and abs(wow_delta) >= $prtf_move
            then 'ANOMALY'
        when wow_pct is null or abs(wow_pct) < $wow then 'FLAT'
        when wow_pct > 0 then 'UP'
        else 'DOWN'
    end as flag,
    case
        when kpi_code = 'PRTF_CONTACT_12M' then
            case when wow_delta - move_avg >= 0 then 'UP' else 'DOWN' end
        else case when value - baseline_avg >= 0 then 'UP' else 'DOWN' end
    end as anomaly_direction
from backtest_report
"""


def _connect(data_dir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(data_dir / WAREHOUSE_FILE), read_only=True)
    con.execute(_PREPARE)
    return con


def _flag_rows(con: duckdb.DuckDBPyConnection, t: Thresholds) -> list[tuple[object, ...]]:
    params = {
        "z": t.z,
        "min_weeks": t.min_baseline_weeks,
        "prtf_z": t.prtf_z,
        "prtf_move": t.prtf_min_move,
        "wow": t.wow_pct,
    }
    return con.execute(_FLAGS, params).fetchall()


def mismatches(con: duckdb.DuckDBPyConnection) -> int:
    """Rows where the re-run rules at the shipped thresholds disagree with the mart."""
    return sum(1 for row in _flag_rows(con, SHIPPED) if row[5] != row[6])


@dataclass(frozen=True)
class _Flag:
    week: str
    week_start: date
    level: str
    node_id: str
    kpi: str
    rule: str
    direction: str


def flags(con: duckdb.DuckDBPyConnection, t: Thresholds) -> list[_Flag]:
    out = []
    for week, start, level, node, kpi, _mart, flag, anomaly_dir in _flag_rows(con, t):
        if flag == "FLAT":
            continue
        if flag == "ANOMALY":
            rule = "PRTF_MOVE" if kpi == "PRTF_CONTACT_12M" else "ANOMALY"
            direction = str(anomaly_dir)
        else:
            rule = direction = str(flag)
        assert isinstance(start, date)
        out.append(_Flag(str(week), start, str(level), str(node), str(kpi), rule, direction))
    return out


def _rule_kpis(rule: str, kpis: Iterable[str]) -> set[str]:
    kpis = set(kpis)
    if rule == "ANOMALY":
        return kpis - {"PRTF_CONTACT_12M"}
    if rule == "PRTF_MOVE":
        return kpis & {"PRTF_CONTACT_12M"}
    return kpis


def _matches(flag: _Flag, kpis: Iterable[str], story: Story) -> bool:
    return (
        flag.kpi in kpis
        and flag.direction == story.direction
        and story.start_week <= flag.week <= story.end_week
    )


def score(truth: GroundTruth, found: Sequence[_Flag], node_weeks: dict[str, int]) -> list[Score]:
    """Precision, recall, lag and false alarms per rule and level."""
    calendar = set(truth.calendar_weeks)
    volume_kpis = {k for s in truth.stories if s.story == "DISTRICT_VOLUME" for k in s.kpis}
    by_node: dict[tuple[str, str], list[Story]] = {}
    for story in truth.stories:
        by_node.setdefault((story.level, story.node_id), []).append(story)
    scores: list[Score] = []
    for rule in RULES:
        for level in LEVELS:
            in_scope = [
                s
                for s in truth.stories
                if s.level == level
                and s.scored
                and _rule_kpis(rule, s.kpis)
                and (rule not in ("UP", "DOWN") or s.direction == rule)
            ]
            first_hit: dict[Story, str] = {}
            hits = explained = false = calendar_false = total = 0
            for flag in found:
                if flag.rule != rule or flag.level != level:
                    continue
                total += 1
                candidates = by_node.get((level, flag.node_id), [])
                matched = [s for s in candidates if s.scored and _matches(flag, s.kpis, s)]
                if matched:
                    hits += 1
                    for s in matched:
                        first_hit[s] = min(first_hit.get(s, flag.week), flag.week)
                elif any(_matches(flag, s.kpis, s) for s in candidates):
                    explained += 1
                else:
                    false += 1
                    calendar_false += flag.week in calendar and flag.kpi in volume_kpis
            lags = [_weeks_between(s.start_week, first_hit[s]) for s in in_scope if s in first_hit]
            weeks = node_weeks.get(level, 0)
            scores.append(
                Score(
                    seed=truth.seed,
                    rule=rule,
                    level=level,
                    stories=len(in_scope),
                    detected=len(lags),
                    recall=round(len(lags) / len(in_scope), 3) if in_scope else None,
                    median_lag_weeks=statistics.median(lags) if lags else None,
                    flags=total,
                    hits=hits,
                    explained=explained,
                    false_alarms=false,
                    calendar_false_alarms=calendar_false,
                    precision=round((hits + explained) / total, 3) if total else None,
                    node_weeks=weeks,
                    false_per_100_node_weeks=round(100 * false / weeks, 2) if weeks else 0.0,
                )
            )
    return scores


def _weeks_between(first: str, last: str) -> int:
    def monday(week: str) -> date:
        year, number = week.split("-W")
        return date.fromisocalendar(int(year), int(number), 1)

    return (monday(last) - monday(first)).days // 7


def _node_weeks(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    rows = con.execute(
        "select level, count(distinct (iso_week_id, node_id)) from backtest_report group by 1"
    ).fetchall()
    return {str(level): int(n) for level, n in rows}


def _weeks(con: duckdb.DuckDBPyConnection) -> tuple[date, date, str]:
    row = con.execute(
        "select min(week_start), max(week_start), max(iso_week_id) from backtest_report"
    ).fetchone()
    assert row is not None
    return row[0], row[1], row[2]
