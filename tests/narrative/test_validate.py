from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from pulse.contracts.enums import KpiCode, RunType, StageStatus
from pulse.contracts.exports import NarrativeBullet, NarrativeFact, NodeNarrative, WeeklyReport
from pulse.narrative.facts import NodeFacts, build_facts, narrated_nodes
from pulse.narrative.fallback import generate_guarded
from pulse.narrative.generate import ResponseCache, cache_key, narrate_node
from pulse.narrative.stage import write_narratives
from pulse.narrative.template import template_narrative
from pulse.narrative.validate import validate

ROOT = Path(__file__).parents[2]
REPORT = ROOT / "fixtures" / "exports" / "weekly_report.parquet"
WEEK = "2026-W40"


@pytest.fixture(scope="module")
def report() -> list[WeeklyReport]:
    return [WeeklyReport.model_validate(r) for r in pq.read_table(REPORT).to_pylist()]


@pytest.fixture(scope="module")
def on(report: list[WeeklyReport]) -> NodeFacts:
    return build_facts(report, "ON", WEEK)


def fact(node: NodeFacts, node_id: str, kpi: KpiCode) -> NarrativeFact:
    return next(
        f
        for f in node.facts
        if f.node_id == node_id and f.kpi_code is kpi and f.iso_week_id == node.iso_week_id
    )


def narrative(node: NodeFacts, headline: str, *bullets: tuple[str, list[str]]) -> NodeNarrative:
    return NodeNarrative(
        node_id=node.node_id,
        level=node.level,
        headline=headline,
        bullets=[NarrativeBullet(text=t, fact_ids=ids) for t, ids in bullets]
        or [NarrativeBullet(text="Weekly summary.", fact_ids=["F1"])],
        facts_used=list(node.facts),
        model="claude-opus-5-5",
        prompt_version="narrative-v1",
        validated=True,
        fallback=False,
    )


def kinds(n: NodeNarrative) -> list[str]:
    return [p.kind for p in validate(n)]


# ── The three failures the issue names ──────────────────────────────────────


def test_fabricated_number_is_caught(on: NodeFacts) -> None:
    show = fact(on, "ON", KpiCode.SHOW_RATE)  # 83.3%
    problems = validate(narrative(on, "Ontario weekly.", ("Show rate 97.0%.", [show.fact_id])))
    assert [p.kind for p in problems] == ["fabricated"]
    assert "97.0% matches no cited fact" in str(problems[0])


def test_wrong_sign_on_a_delta_is_caught(on: NodeFacts) -> None:
    lead = fact(on, "ON", KpiCode.ACT_PER_ADV)  # +3.4% wow, to 10.4
    assert lead.wow_pct is not None and lead.wow_pct > 0
    right = narrative(on, "Ontario: activities per advisor rose 3.4% week over week to 10.4.")
    wrong = narrative(on, "Ontario: activities per advisor fell 3.4% week over week to 10.4.")
    assert kinds(right) == []
    assert kinds(wrong) == ["wrong_sign"]


def test_wrong_sign_on_percentage_points(on: NodeFacts) -> None:
    show = fact(on, "ON", KpiCode.SHOW_RATE)  # 90.0% -> 83.3%: down 6.7 points
    ids = [show.fact_id]
    assert kinds(narrative(on, "x", ("Show rate down 6.7 percentage points.", ids))) == []
    assert kinds(narrative(on, "x", ("Show rate up 6.7 percentage points.", ids))) == ["wrong_sign"]


def test_uncited_claim_is_caught(on: NodeFacts) -> None:
    calls = fact(on, "ON", KpiCode.CALLS_OUT)
    gta = fact(on, "GTA", KpiCode.COVERAGE_13W)  # 85.9%
    text = "GTA trails its peers on 13-week coverage at 85.9%."
    problems = validate(narrative(on, "x", (text, [calls.fact_id])))
    assert [p.kind for p in problems] == ["uncited"]
    assert f"matches {gta.fact_id}, which is not cited" in str(problems[0])
    assert kinds(narrative(on, "x", (text, [gta.fact_id]))) == []


# ── Tolerance and non-claims ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("shown", "ok"), [("3%", True), ("3.4%", True), ("3.37%", True), ("3.5%", False)]
)
def test_rounding_tolerance_follows_the_digits_shown(on: NodeFacts, shown: str, ok: bool) -> None:
    lead = fact(on, "ON", KpiCode.ACT_PER_ADV)
    n = narrative(on, "x", (f"Activities per advisor rose {shown}.", [lead.fact_id]))
    assert (kinds(n) == []) is ok


def test_ids_weeks_and_window_wording_are_not_claims(on: NodeFacts) -> None:
    text = "In 2026-W40, BR-0101 and F1 stayed on the 13-week view; 12 weeks of history."
    assert kinds(narrative(on, text)) == []


def test_rank_and_peer_count_are_grounded(on: NodeFacts) -> None:
    gta = fact(on, "GTA", KpiCode.COVERAGE_13W)
    assert gta.rank_in_parent is not None and gta.peer_count is not None
    text = f"GTA ranks {gta.rank_in_parent} of {gta.peer_count} on 13-week coverage."
    assert kinds(narrative(on, "x", (text, [gta.fact_id]))) == []


@pytest.mark.parametrize(
    "text",
    [
        "Live numbers for Ontario.",
        "Real-time view of Ontario.",
        "Advisors should book more reviews.",
        "Coverage fell because advisors were on leave.",
        "This is likely due to holidays.",
    ],
)
def test_banned_phrases(on: NodeFacts, text: str) -> None:
    assert "banned" in kinds(narrative(on, text))


def test_templates_pass_the_validator(report: list[WeeklyReport]) -> None:
    for week in ("2026-W39", "2026-W40"):
        for node_id, _ in narrated_nodes(report, week):
            node = build_facts(report, node_id, week)
            assert validate(template_narrative(node)) == [], (week, node_id)


# ── Regeneration and fallback ───────────────────────────────────────────────


class Scripted:
    """Returns the scripted answers in order; records the messages it was sent."""

    model = "claude-opus-5-5"

    def __init__(self, *answers: dict[str, Any] | Exception) -> None:
        self.answers = list(answers)
        self.messages: list[str] = []

    def complete(self, user: str) -> dict[str, Any]:
        self.messages.append(user)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def answer(text: str, fact_id: str) -> dict[str, Any]:
    return {
        "headline": "Ontario weekly.",
        "bullets": [{"text": text, "fact_ids": [fact_id]}],
        "watchlist": [],
    }


def test_one_regeneration_with_feedback_then_accept(on: NodeFacts, tmp_path: Path) -> None:
    show = fact(on, "ON", KpiCode.SHOW_RATE)
    client = Scripted(
        answer("Show rate 97.0%.", show.fact_id), answer("Show rate 83.3%.", show.fact_id)
    )
    outcome = narrate_node(on, client, ResponseCache(tmp_path))
    assert not outcome.narrative.fallback and outcome.narrative.validated
    assert len(client.messages) == 2
    assert "failed validation" in client.messages[1] and "97.0%" in client.messages[1]
    # The accepted (second) answer is what gets cached.
    cached = ResponseCache(tmp_path).get(cache_key(client.model, on))
    assert cached is not None and cached["bullets"][0]["text"] == "Show rate 83.3%."


def test_two_failures_fall_back_to_the_template(on: NodeFacts, tmp_path: Path) -> None:
    show = fact(on, "ON", KpiCode.SHOW_RATE)
    bad = answer("Show rate 97.0%.", show.fact_id)
    client = Scripted(bad, bad)
    outcome = narrate_node(on, client, ResponseCache(tmp_path))
    assert outcome.narrative.fallback and outcome.narrative.model is None
    assert (outcome.reason or "").startswith("failed validation: bullet 1: fabricated")
    assert len(client.messages) == 2
    assert not list(tmp_path.glob("*.json"))


def test_cached_answer_that_now_fails_is_regenerated(on: NodeFacts, tmp_path: Path) -> None:
    show = fact(on, "ON", KpiCode.SHOW_RATE)
    cache = ResponseCache(tmp_path)
    cache.put(cache_key("claude-opus-5-5", on), answer("Show rate 97.0%.", show.fact_id))
    client = Scripted(answer("Show rate 83.3%.", show.fact_id))
    outcome = narrate_node(on, client, cache)
    assert not outcome.narrative.fallback and not outcome.cached
    assert len(client.messages) == 1 and "failed validation" in client.messages[0]


def test_guarded_reports_attempts(on: NodeFacts) -> None:
    lead = fact(on, "ON", KpiCode.ACT_PER_ADV)
    good = generate_guarded(on, Scripted(answer("Activities per advisor 10.4.", lead.fact_id)))
    assert (good.attempts, good.reason) == (1, None)


def test_api_down_gives_every_node_the_template(report: list[WeeklyReport], tmp_path: Path) -> None:
    class Down:
        model = "claude-opus-5-5"

        def complete(self, user: str) -> dict[str, Any]:
            raise ConnectionError("API unreachable")

    from datetime import UTC, datetime

    from pulse.runner.stage import StageContext

    class Clock:
        def now(self) -> datetime:
            return datetime(2026, 10, 5, tzinfo=UTC)

        def sleep(self, seconds: float) -> None:
            pass

    ctx = StageContext("manual-2026-W40-1", RunType.MANUAL, WEEK, tmp_path, Clock())
    result = write_narratives(report, WEEK, tmp_path, Down(), ctx)
    assert result.status is StageStatus.WARN
    assert (
        result.message
        == "5 of 5 narratives fell back to the template (API error: ConnectionError)."
    )
    from pulse.contracts.exports import NarrativeFile

    doc = NarrativeFile.model_validate_json((tmp_path / f"{WEEK}.json").read_text())
    assert [n.fallback for n in doc.narratives] == [True] * 5
    assert all(validate(n) == [] for n in doc.narratives)
