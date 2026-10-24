"""The generator's ground truth comes from the seed and the generator's own story rules."""

from __future__ import annotations

import json
from datetime import date
from functools import cache
from pathlib import Path

from pulse.contracts.enums import Role
from pulse.generate import truth as truth_module
from pulse.generate.activity import DRIFT_SHARE, default_story_districts, is_drifter
from pulse.generate.advisors import REPORT_START, assignment_ranges
from pulse.generate.cli import Sizes, World, build_world
from pulse.generate.truth import (
    TRUTH_FILE,
    GroundTruth,
    calendar_weeks,
    ground_truth,
    write_ground_truth,
)
from pulse.reference import org

LAST = date(2026, 10, 12)


@cache
def _world(seed: int) -> World:
    return build_world(seed, Sizes(advisors=120, clients=3000), "2026-W42")


def _truth(seed: int) -> GroundTruth:
    world = _world(seed)
    return ground_truth(
        org(),
        assignment_ranges(world.roster),
        world.clients,
        world.portfolios,
        seed=seed,
        first=REPORT_START,
        last=LAST,
    )


def test_the_story_districts_fall_and_rise_by_a_third_from_story_start() -> None:
    falling, rising = default_story_districts(org())
    stories = {
        (s.node_id, s.direction, s.effect, s.start_week, s.full_week, s.end_week)
        for s in _truth(7).stories
        if s.story == "DISTRICT_VOLUME" and s.level == "DISTRICT"
    }
    assert stories == {
        (falling, "DOWN", -0.35, "2026-W34", "2026-W40", "2026-W53"),
        (rising, "UP", 0.35, "2026-W34", "2026-W40", "2026-W53"),
    }


def test_every_staffed_branch_of_a_story_district_is_a_scored_story() -> None:
    falling, rising = default_story_districts(org())
    story_branches = {
        p.branch.branch_id
        for p in org().placements()
        if p.district.district_code in (falling, rising)
    }
    volume = [s for s in _truth(7).stories if s.story == "DISTRICT_VOLUME"]
    branches = [s for s in volume if s.level == "BRANCH"]
    # At test size some branches have no advisors; every staffed one is a full-size story.
    assert branches and {s.node_id for s in branches} <= story_branches
    assert all(s.scored and abs(s.effect) == 0.35 for s in branches)
    # The national effect is a small net of the two, too small to count as a story.
    national = [s for s in volume if s.level == "NATIONAL"]
    assert all(not s.scored and abs(s.effect) < 0.05 for s in national)


def test_drift_stories_are_downward_and_follow_the_seeded_drifters() -> None:
    truth = _truth(7)
    drift = [s for s in truth.stories if s.story == "PORTFOLIO_DRIFT"]
    assert drift and all(s.direction == "DOWN" and s.effect < 0 for s in drift)
    assert all(s.kpis == ("PRTF_CONTACT_12M",) for s in drift)
    assert {s.start_week for s in drift} == {"2025-W45"}
    advisors = {a.advisor_id for a in _world(7).roster.advisors}
    share = sum(is_drifter(7, a) for a in advisors) / len(advisors)
    assert abs(share - DRIFT_SHARE) < 0.08


def test_the_truth_is_deterministic_and_depends_on_the_seed(tmp_path: Path) -> None:
    once, again = _truth(7), _truth(7)
    assert once.to_json() == again.to_json()
    path = write_ground_truth(once, tmp_path)
    assert path == tmp_path / TRUTH_FILE
    assert json.loads(path.read_text())["seed"] == 7
    other = _truth(8)
    drift = {s.node_id for s in once.stories if s.story == "PORTFOLIO_DRIFT" and s.scored}
    drift_other = {s.node_id for s in other.stories if s.story == "PORTFOLIO_DRIFT" and s.scored}
    assert drift != drift_other


def test_calendar_weeks_are_holidays_february_and_the_weeks_after() -> None:
    weeks = calendar_weeks(date(2026, 1, 1), date(2026, 12, 31))
    assert "2026-W42" in weeks  # Thanksgiving Monday, 12 October
    assert "2026-W43" in weeks  # the week after it
    assert "2026-W06" in weeks  # the February lift starts
    assert "2026-W33" not in weeks  # an ordinary August week


def test_advisor_events_identify_the_seeded_sources_of_the_aggregate_stories() -> None:
    events = [s for s in _truth(7).stories if s.level == "ADVISOR"]
    drift = [s for s in events if s.story == "PORTFOLIO_DRIFT"]
    volume = [s for s in events if s.story == "DISTRICT_VOLUME"]
    assert drift and volume
    assert all(is_drifter(7, s.node_id) and s.direction == "DOWN" for s in drift)
    assert min(s.start_week for s in drift) == "2025-W45"
    assert {s.direction for s in volume} == {"UP", "DOWN"}
    assert all(s.node_id.startswith("ADV-") for s in events)


def test_a_sunday_hire_changes_volume_only_when_the_advisor_can_first_work() -> None:
    branch = next(
        p.branch.branch_id for p in org().placements() if p.district.district_code == "BCI"
    )
    events = truth_module._advisor_stories(
        org(), [("ADV-12345", branch, Role.ADVISOR, date(2026, 10, 4), None)], 7, LAST
    )
    volume = next(s for s in events if s.story == "DISTRICT_VOLUME")
    assert volume.start_week == "2026-W41"  # Monday October 5; no activities on Sunday
