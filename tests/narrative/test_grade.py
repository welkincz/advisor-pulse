"""Each grader rule, with a passing and a failing narrative."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pulse.contracts.enums import KpiCode, OrgLevel
from pulse.contracts.exports import NarrativeBullet, NarrativeFact, NodeNarrative, WatchItem
from pulse.narrative.facts import NodeFacts
from pulse.narrative.grade import below_floor, grade, reading_grade, summarize
from pulse.narrative.prompt import MAX_WATCHLIST, SYSTEM

WEEK = "2026-W42"


def _fact(fact_id: str, node: str, kpi: KpiCode, value: float, wow: float) -> NarrativeFact:
    return NarrativeFact(
        fact_id=fact_id,
        node_id=node,
        kpi_code=kpi,
        iso_week_id=WEEK,
        value=value,
        wow_pct=wow,
    )


NODE = NodeFacts(
    node_id="GTA",
    node_name="Greater Toronto",
    level=OrgLevel.DISTRICT,
    iso_week_id=WEEK,
    children={"BR-1": "King", "BR-2": "Bay"},
    facts=(
        _fact("F1", "GTA", KpiCode.PRTF_CONTACT_12M, 0.869, -0.001),
        _fact("F2", "GTA", KpiCode.SHOW_RATE, 0.9, 0.02),
        _fact("F3", "GTA", KpiCode.APPT_CONV, 0.4, 0.05),
        _fact("F4", "GTA", KpiCode.CALL_TO_APPT, 0.3, 0.03),
        _fact("F5", "BR-1", KpiCode.SHOW_RATE, 0.8, -0.1),
    ),
)
HEADLINE = "Portfolio contacted (12 months) fell 0.1% this week to 86.9%."


def _good(**changes: object) -> NodeNarrative:
    base: dict[str, object] = {
        "node_id": "GTA",
        "level": OrgLevel.DISTRICT,
        "headline": HEADLINE,
        "bullets": [
            NarrativeBullet(text="Portfolio contacted (12 months) was 86.9%.", fact_ids=["F1"]),
            NarrativeBullet(text="Show rate rose 2.0% to 90.0%.", fact_ids=["F2"]),
        ],
        "watchlist": [],
        "facts_used": list(NODE.facts),
        "model": "recorded",
        "prompt_version": "test",
        "validated": True,
        "fallback": False,
    }
    return NodeNarrative(**{**base, **changes})  # type: ignore[arg-type]


def _bullets(*texts: str) -> list[NarrativeBullet]:
    return [
        NarrativeBullet(text="Portfolio contacted (12 months) was 86.9%.", fact_ids=["F1"]),
        *(NarrativeBullet(text=t, fact_ids=["F2"]) for t in texts),
    ]


def test_a_good_narrative_passes_every_rule() -> None:
    assert grade(_good(), NODE).failed == ()


@pytest.mark.parametrize(
    ("rule", "narrative", "node"),
    [
        (
            "grounded",
            _good(bullets=_bullets("Show rate rose 2.0% to 77.7%.")),
            NODE,
        ),
        ("anomalies", _good(), replace(NODE, anomalies=("F3",))),
        ("lead_first", _good(headline="Show rate rose 2.0% this week to 90.0%."), NODE),
        (
            "lead_first",
            _good(
                bullets=[
                    NarrativeBullet(text="Show rate rose 2.0% to 90.0%.", fact_ids=["F2"]),
                    NarrativeBullet(text="Portfolio contacted was 86.9%.", fact_ids=["F1"]),
                ]
            ),
            NODE,
        ),
        ("length", _good(headline=f"{HEADLINE} {'a' * 120}"), NODE),
        ("length", _good(bullets=_bullets()), NODE),
        ("length", _good(bullets=_bullets("word " * 41)), NODE),
        (
            "reading_level",
            _good(
                bullets=_bullets(
                    "Organizational intermediation characteristically necessitates "
                    "institutionalized administrative reconsideration."
                )
            ),
            NODE,
        ),
        ("wording", _good(bullets=_bullets("Show rate had a stellar week at 90.0%.")), NODE),
        ("wording", _good(bullets=_bullets("This live view shows a 90.0% show rate.")), NODE),
        ("one_claim", _good(bullets=_bullets("Show rate was 90.0%. It rose 2.0%.")), NODE),
        (
            "one_claim",
            _good(
                bullets=[
                    NarrativeBullet(text="Portfolio contacted was 86.9%.", fact_ids=["F1"]),
                    NarrativeBullet(
                        text="Show rate was 90.0%, conversion 40.0% and call rate 30.0%.",
                        fact_ids=["F2", "F3", "F4"],
                    ),
                ]
            ),
            NODE,
        ),
        ("no_cause", _good(bullets=_bullets("Show rate rose 2.0% due to reminders.")), NODE),
        (
            "action",
            _good(
                bullets=[
                    *_bullets(),
                    NarrativeBullet(text="BR-1 show rate fell 10.0% to 80.0%.", fact_ids=["F5"]),
                ]
            ),
            replace(NODE, anomalies=("F5",)),
        ),
    ],
)
def test_each_rule_fails_its_example(rule: str, narrative: NodeNarrative, node: NodeFacts) -> None:
    assert rule in grade(narrative, node).failed


def test_a_flagged_child_on_the_watchlist_passes_the_action_rule() -> None:
    narrative = _good(
        bullets=[
            *_bullets(),
            NarrativeBullet(text="BR-1 show rate fell 10.0% to 80.0%.", fact_ids=["F5"]),
        ],
        watchlist=[WatchItem(node_id="BR-1", reason="Show rate was 80.0%.", fact_ids=["F5"])],
    )
    assert grade(narrative, replace(NODE, anomalies=("F5",))).failed == ()


# Four flagged children: one more than the prompt lets the watchlist hold.
CROWDED = replace(
    NODE,
    children={f"BR-{i}": f"Branch {i}" for i in range(1, 5)},
    facts=(
        *NODE.facts[:4],
        *(_fact(f"F{i + 4}", f"BR-{i}", KpiCode.SHOW_RATE, 0.8, -0.1) for i in range(1, 5)),
    ),
    anomalies=("F5", "F6", "F7", "F8"),
)


def _watching(*children: int) -> NodeNarrative:
    return _good(
        facts_used=list(CROWDED.facts),
        bullets=[
            *_bullets(),
            NarrativeBullet(
                text="Four branches had a flagged show rate of 80.0%.",
                fact_ids=["F5", "F6", "F7", "F8"],
            ),
        ],
        watchlist=[
            WatchItem(node_id=f"BR-{i}", reason="Show rate was 80.0%.", fact_ids=[f"F{i + 4}"])
            for i in children
        ],
    )


def test_the_prompt_states_the_watchlist_cap_the_grader_uses() -> None:
    assert f"watchlist: 0 to {MAX_WATCHLIST} child nodes" in SYSTEM


@pytest.mark.parametrize("children", [(1, 2, 3), (4, 2, 1), (2, 3, 4)])
def test_a_full_watchlist_passes_when_more_children_are_flagged_than_fit(
    children: tuple[int, ...],
) -> None:
    assert len(children) == MAX_WATCHLIST
    assert "action" not in grade(_watching(*children), CROWDED).failed


def test_a_short_watchlist_fails_when_more_children_are_flagged_than_fit() -> None:
    assert "action" in grade(_watching(1, 2), CROWDED).failed


def test_a_flag_that_is_cited_passes_the_anomalies_rule() -> None:
    assert grade(_good(), replace(NODE, anomalies=("F2",))).failed == ()


def test_reading_grade_ignores_figures() -> None:
    assert reading_grade("Rate was 86.9%.") == reading_grade("Rate was 12.3456%.")
    assert reading_grade("") == 0.0


def test_summary_and_floor() -> None:
    good, bad = grade(_good(), NODE), grade(_good(headline="Nothing to see."), NODE)
    assert summarize([good, good, bad]) == "Grader: 2 of 3 narratives pass."
    assert below_floor([good, bad]) is True
    assert below_floor([good] * 4 + [bad]) is False
    assert below_floor([]) is False
