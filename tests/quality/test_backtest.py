"""The backtest re-runs the mart's flag rules and scores them against the ground truth."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from pulse.generate.truth import GroundTruth, Story
from pulse.quality import backtest
from pulse.quality.backtest import PREVIOUS, SHIPPED, flags, mismatches, score
from pulse.warehouse import WAREHOUSE_FILE

# The dbt unit test's series (mart_weekly_report.yml): steady near 100, then 120 in W09.
CALLS = [100, 104, 96, 100, 104, 96, 100, 100, 120]
MART_FLAGS = ["FLAT", "UP", "DOWN", "UP", "UP", "DOWN", "UP", "FLAT", "ANOMALY"]


def _warehouse(tmp_path: Path, mart_flags: list[str]) -> duckdb.DuckDBPyConnection:
    path = tmp_path / WAREHOUSE_FILE
    con = duckdb.connect(str(path))
    con.execute("create schema marts")
    con.execute("create table marts.dim_date (iso_week_id varchar, week_start date)")
    con.execute(
        "create table marts.mart_weekly_report (iso_week_id varchar, level varchar,"
        " node_id varchar, kpi_code varchar, value double, wow_delta double,"
        " wow_pct double, flag varchar)"
    )
    prior = None
    for i, (value, flag) in enumerate(zip(CALLS, mart_flags, strict=True)):
        week = f"2026-W{i + 1:02d}"
        con.execute(
            "insert into marts.dim_date values (?, ?)",
            [week, date(2025, 12, 29) + timedelta(weeks=i)],
        )
        delta = None if prior is None else value - prior
        pct = None if prior is None else round(delta / prior, 4)
        con.execute(
            "insert into marts.mart_weekly_report"
            " values (?, 'BRANCH', 'BR-1', 'CALLS_OUT', ?, ?, ?, ?)",
            [week, value, delta, pct, flag],
        )
        prior = value
    con.close()
    return backtest._connect(tmp_path)


def _truth(scored: bool = True) -> GroundTruth:
    story = Story(
        story="DISTRICT_VOLUME",
        level="BRANCH",
        node_id="BR-1",
        direction="UP",
        kpis=("CALLS_OUT",),
        related_kpis=(),
        start_week="2026-W08",
        full_week="2026-W09",
        end_week="2026-W12",
        effect=0.2,
        scored=scored,
    )
    return GroundTruth(seed=1, stories=(story,), calendar_weeks=("2026-W06",))


def test_the_rerun_rules_reproduce_the_mart_flags(tmp_path: Path) -> None:
    con = _warehouse(tmp_path, MART_FLAGS)
    assert mismatches(con) == 0


def test_a_mart_built_with_other_thresholds_is_caught(tmp_path: Path) -> None:
    con = _warehouse(tmp_path, [*MART_FLAGS[:-1], "UP"])
    assert mismatches(con) == 1


def test_a_story_flagged_one_week_in_is_a_hit_with_a_lag_of_one(tmp_path: Path) -> None:
    con = _warehouse(tmp_path, MART_FLAGS)
    scores = {(s.rule, s.level): s for s in score(_truth(), flags(con, SHIPPED), {"BRANCH": 9})}
    anomaly = scores[("ANOMALY", "BRANCH")]
    assert (anomaly.stories, anomaly.detected, anomaly.median_lag_weeks) == (1, 1, 1)
    assert (anomaly.hits, anomaly.false_alarms, anomaly.precision) == (1, 0, 1.0)
    moves = scores[("DOWN", "BRANCH")]
    # Two downward labels before the story starts, one in a calendar week. The upward
    # story is not eligible for recall from a DOWN label.
    assert (moves.hits, moves.false_alarms, moves.calendar_false_alarms) == (0, 2, 1)
    assert moves.recall is None
    assert moves.false_per_100_node_weeks == pytest.approx(22.22)


def test_a_small_exposure_explains_a_flag_without_scoring_it(tmp_path: Path) -> None:
    con = _warehouse(tmp_path, MART_FLAGS)
    scores = {(s.rule, s.level): s for s in score(_truth(scored=False), flags(con, SHIPPED), {})}
    anomaly = scores[("ANOMALY", "BRANCH")]
    assert (anomaly.stories, anomaly.recall, anomaly.explained, anomaly.false_alarms) == (
        0,
        None,
        1,
        0,
    )


def test_a_stricter_threshold_misses_the_story(tmp_path: Path) -> None:
    con = _warehouse(tmp_path, MART_FLAGS)
    strict = replace(SHIPPED, z=10.0)
    anomaly = next(
        s
        for s in score(_truth(), flags(con, strict), {})
        if s.rule == "ANOMALY" and s.level == "BRANCH"
    )
    assert anomaly.recall == 0.0 and anomaly.median_lag_weeks is None
    assert PREVIOUS.z < SHIPPED.z


def test_precision_counts_direct_small_stories_but_not_indirect_overlaps() -> None:
    story = _truth().stories[0]
    small = replace(story, node_id="BR-2", scored=False)
    indirect = replace(story, node_id="BR-3", kpis=("APPT_BOOKED",), related_kpis=("CALLS_OUT",))
    truth = GroundTruth(seed=1, stories=(story, small, indirect), calendar_weeks=())
    found = [
        backtest._Flag("2026-W09", date(2026, 2, 23), "BRANCH", node, "CALLS_OUT", "ANOMALY", "UP")
        for node in ("BR-1", "BR-2", "BR-3", "BR-4")
    ]
    result = next(
        s
        for s in score(truth, found, {"BRANCH": 100})
        if s.rule == "ANOMALY" and s.level == "BRANCH"
    )
    # Two directly affected nodes out of all four flags; indirect overlap is not proof.
    assert result.precision == 0.5
    assert (result.hits, result.explained, result.false_alarms) == (1, 1, 2)


def test_operational_kpi_flags_are_included(tmp_path: Path) -> None:
    con = _warehouse(tmp_path, MART_FLAGS)
    con.execute(
        "update backtest_report set kpi_code = 'LATE_RATE', level = 'NATIONAL', node_id = 'CA'"
    )
    found = flags(con, SHIPPED)
    assert any(f.kpi == "LATE_RATE" and f.rule == "ANOMALY" for f in found)
    assert any(f.kpi == "LATE_RATE" and f.rule == "DOWN" for f in found)
