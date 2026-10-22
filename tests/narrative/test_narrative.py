from __future__ import annotations

import json
import os
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from pulse.contracts.enums import KpiCode, OrgLevel, RunType, StageStatus
from pulse.contracts.exports import NarrativeFile, WeeklyReport
from pulse.narrative.client import AnthropicClient
from pulse.narrative.facts import HEADLINE_KPI, build_facts, narrated_nodes
from pulse.narrative.generate import ResponseCache, cache_key, narrate_node
from pulse.narrative.prompt import KPI_LABELS, PROMPT_VERSION, facts_json, fmt, user_message
from pulse.narrative.stage import narrate, write_narratives
from pulse.narrative.template import template_narrative
from pulse.runner.stage import StageContext
from pulse.runner.stages import load_narratives
from pulse.warehouse import WAREHOUSE_FILE, connect

ROOT = Path(__file__).parents[2]
REPORT_PARQUET = ROOT / "fixtures" / "exports" / "weekly_report.parquet"
WEEK = "2026-W40"
T0 = datetime(2026, 10, 5, 11, 0, tzinfo=UTC)
# Read at import: tests/conftest.py removes the key from every test's environment.
LIVE_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


class Clock:
    def now(self) -> datetime:
        return T0

    def sleep(self, seconds: float) -> None:
        pass


@pytest.fixture(scope="module")
def report() -> list[WeeklyReport]:
    return [WeeklyReport.model_validate(r) for r in pq.read_table(REPORT_PARQUET).to_pylist()]


def ctx(data_dir: Path) -> StageContext:
    return StageContext(f"manual-{WEEK}-1", RunType.MANUAL, WEEK, data_dir, Clock())


class FakeClient:
    """Answers like the model would, citing the first fact; records every call."""

    model = "claude-opus-5-5"

    def __init__(self, answer: dict[str, Any] | None = None, error: Exception | None = None):
        self.answer = answer
        self.error = error
        self.calls: list[str] = []

    def complete(self, user: str) -> dict[str, Any]:
        self.calls.append(user)
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer
        # A grounded answer: state F1's value, as the prompt asks.
        first = json.loads(user.split("Facts:\n", 1)[1].splitlines()[0])[0]
        value = fmt(KpiCode(first["kpi_code"]), first["value"])
        return {
            "headline": "Weekly activity summary.",
            "bullets": [
                {"text": f"{KPI_LABELS[KpiCode(first['kpi_code'])]} {value}.", "fact_ids": ["F1"]}
            ],
            "watchlist": [],
        }


# ── Facts ───────────────────────────────────────────────────────────────────


def test_narrated_nodes_are_regions_then_districts(report: list[WeeklyReport]) -> None:
    assert narrated_nodes(report, WEEK) == [
        ("ON", OrgLevel.REGION),
        ("QC", OrgLevel.REGION),
        ("EON", OrgLevel.DISTRICT),
        ("GTA", OrgLevel.DISTRICT),
        ("MTL", OrgLevel.DISTRICT),
    ]


def test_facts_are_deterministic_and_cover_node_children_and_history(
    report: list[WeeklyReport],
) -> None:
    node = build_facts(report, "ON", WEEK)
    shuffled = list(report)
    random.Random(7).shuffle(shuffled)
    assert facts_json(build_facts(shuffled, "ON", WEEK)) == facts_json(node)

    assert [f.fact_id for f in node.facts] == [f"F{i}" for i in range(1, len(node.facts) + 1)]
    current = [f for f in node.facts if f.iso_week_id == WEEK]
    # The node itself: every KPI it reports this week.
    on_kpis = {f.kpi_code for f in current if f.node_id == "ON"}
    assert {KpiCode.ACT_PER_ADV, KpiCode.SHOW_RATE, KpiCode.COVERAGE_13W} <= on_kpis
    # Its children, with peer rank.
    assert set(node.children) == {"EON", "GTA"}
    assert {f.node_id for f in current} == {"ON", "EON", "GTA"}
    assert all(f.peer_count for f in current if f.node_id in node.children)
    # 13-week context: trailing average on every fact, plus the headline KPI's history.
    history = [f for f in node.facts if f.iso_week_id != WEEK]
    assert [f.iso_week_id for f in history] == ["2026-W37", "2026-W38", "2026-W39"]
    assert {(f.node_id, f.kpi_code) for f in history} == {("ON", KpiCode.ACT_PER_ADV)}
    assert all(f.trailing_13w_avg is not None for f in current)


def test_unknown_node_is_an_error(report: list[WeeklyReport]) -> None:
    with pytest.raises(ValueError, match="no weekly_report rows"):
        build_facts(report, "NOPE", WEEK)


def test_prompt_carries_the_facts(report: list[WeeklyReport]) -> None:
    message = user_message(build_facts(report, "GTA", WEEK))
    assert "GTA" in message and '"fact_id":"F1"' in message


def test_prompt_assigns_only_the_nodes_headline_kpi_to_headline(
    report: list[WeeklyReport],
) -> None:
    node = build_facts(report, "GTA", WEEK)
    # The fixtures span 4 weeks: no 12-month window, so activities per advisor leads.
    assert HEADLINE_KPI is KpiCode.PRTF_CONTACT_12M
    assert node.headline_kpi is KpiCode.ACT_PER_ADV
    lead = next(
        f
        for f in node.facts
        if f.node_id == node.node_id and f.iso_week_id == WEEK and f.kpi_code is node.headline_kpi
    )
    message = user_message(node)
    label = KPI_LABELS[node.headline_kpi]
    assert f"Headline KPI: {label} ({node.headline_kpi.value}, {lead.fact_id})" in message
    assert "Other KPIs belong in bullets, never in the headline" in message


# ── Template ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("node_id", ["ON", "QC", "EON", "GTA", "MTL"])
def test_template_is_grounded(report: list[WeeklyReport], node_id: str) -> None:
    node = build_facts(report, node_id, WEEK)
    narrative = template_narrative(node)
    known = set(node.by_id())
    assert narrative.fallback and narrative.model is None
    assert narrative.bullets and all(b.fact_ids for b in narrative.bullets)
    assert {f for b in narrative.bullets for f in b.fact_ids} <= known
    assert {w.node_id for w in narrative.watchlist} <= set(node.children)
    assert "live" not in narrative.headline.lower()


def test_template_headline_states_the_headline_fact(report: list[WeeklyReport]) -> None:
    node = build_facts(report, "ON", WEEK)
    lead = node.facts[0]
    assert lead.kpi_code is KpiCode.ACT_PER_ADV and lead.wow_pct is not None
    text = template_narrative(node).headline
    assert text.startswith("Ontario: activities per advisor ")
    assert f"{abs(lead.wow_pct):.1%}" in text


# ── Model call, validation, cache ───────────────────────────────────────────


def test_model_answer_becomes_a_validated_narrative(
    report: list[WeeklyReport], tmp_path: Path
) -> None:
    node = build_facts(report, "ON", WEEK)
    outcome = narrate_node(node, FakeClient(), ResponseCache(tmp_path))
    n = outcome.narrative
    assert (n.fallback, n.validated, n.model) == (False, True, "claude-opus-5-5")
    assert n.bullets[0].fact_ids == ["F1"]
    assert n.facts_used == list(node.facts)


def test_cache_hit_makes_no_api_call(report: list[WeeklyReport], tmp_path: Path) -> None:
    node = build_facts(report, "ON", WEEK)
    client, cache = FakeClient(), ResponseCache(tmp_path)
    first = narrate_node(node, client, cache)
    second = narrate_node(node, client, cache)
    assert len(client.calls) == 1
    assert (first.cached, second.cached) == (False, True)
    assert second.narrative == first.narrative


def test_cache_key_covers_prompt_model_and_facts(report: list[WeeklyReport]) -> None:
    on, qc = build_facts(report, "ON", WEEK), build_facts(report, "QC", WEEK)
    base = cache_key("claude-opus-5-5", on)
    assert base == cache_key("claude-opus-5-5", build_facts(report, "ON", WEEK))
    assert base != cache_key("claude-sonnet-5-5", on)
    assert PROMPT_VERSION == "narrative-v3"
    assert base != cache_key("claude-opus-5-5", on, prompt_version="narrative-v1")
    assert base != cache_key("claude-opus-5-5", qc)


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (
            {"headline": "x", "bullets": [{"text": "y", "fact_ids": ["F999"]}], "watchlist": []},
            "cites unknown facts F999",
        ),
        (
            {"headline": "x", "bullets": [{"text": "y", "fact_ids": []}], "watchlist": []},
            "breaks the narrative contract",
        ),
        ({"headline": "x", "bullets": [], "watchlist": []}, "breaks the narrative contract"),
        (
            {
                "headline": "x",
                "bullets": [{"text": "y", "fact_ids": ["F1"]}],
                "watchlist": [{"node_id": "MTL", "reason": "z", "fact_ids": ["F1"]}],
            },
            "non-child nodes MTL",
        ),
    ],
)
def test_unusable_answer_falls_back_and_is_not_cached(
    report: list[WeeklyReport], tmp_path: Path, answer: dict[str, Any], reason: str
) -> None:
    node = build_facts(report, "ON", WEEK)
    outcome = narrate_node(node, FakeClient(answer), ResponseCache(tmp_path))
    assert outcome.narrative.fallback
    assert reason in (outcome.reason or "")
    assert not list(tmp_path.glob("*.json"))


def test_api_error_falls_back(report: list[WeeklyReport], tmp_path: Path) -> None:
    node = build_facts(report, "ON", WEEK)
    outcome = narrate_node(node, FakeClient(error=TimeoutError("slow")), ResponseCache(tmp_path))
    assert outcome.narrative.fallback
    assert outcome.reason == "API error: TimeoutError"


# ── Stage ───────────────────────────────────────────────────────────────────


def test_without_api_key_the_stage_writes_templates_and_warns(
    report: list[WeeklyReport], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert AnthropicClient.from_env() is None
    result = write_narratives(report, WEEK, tmp_path, AnthropicClient.from_env(), ctx(tmp_path))
    assert result.status is StageStatus.WARN
    assert result.message == "No model backend configured: wrote 5 template narratives."
    doc = NarrativeFile.model_validate_json((tmp_path / f"{WEEK}.json").read_text())
    assert len(doc.narratives) == 5 and all(n.fallback for n in doc.narratives)


def _warehouse_with_report(data_dir: Path) -> None:
    con = connect(data_dir / WAREHOUSE_FILE)
    try:
        con.execute("create schema marts")
        con.execute(
            "create table marts.mart_weekly_report as "
            f"select * from read_parquet('{REPORT_PARQUET}')"
        )
    finally:
        con.close()


def test_stage_reads_the_mart_and_export_picks_up_the_file(tmp_path: Path) -> None:
    _warehouse_with_report(tmp_path)
    client = FakeClient()
    result = narrate(ctx(tmp_path), client_factory=lambda: client)
    assert result.status is StageStatus.SUCCESS, result.message
    assert result.message == "5 narratives validated (0 from cache)."
    assert len(client.calls) == 5

    again = narrate(ctx(tmp_path), client_factory=lambda: client)
    assert again.message == "5 narratives validated (5 from cache)."
    assert len(client.calls) == 5

    published = load_narratives(tmp_path)  # what the export stage reads
    assert list(published) == [WEEK]
    assert [n.node_id for n in published[WEEK].narratives] == ["ON", "QC", "EON", "GTA", "MTL"]


def test_partial_fallback_warns_with_the_reason(tmp_path: Path) -> None:
    _warehouse_with_report(tmp_path)
    bad = {"headline": "x", "bullets": [{"text": "y", "fact_ids": ["F999"]}], "watchlist": []}
    result = narrate(ctx(tmp_path), client_factory=lambda: FakeClient(bad))
    assert result.status is StageStatus.WARN
    assert result.message == (
        "5 of 5 narratives fell back to the template (failed validation: cites unknown facts F999)."
    )


def test_stage_skips_until_the_mart_exists(tmp_path: Path) -> None:
    assert narrate(ctx(tmp_path), client_factory=FakeClient).status is StageStatus.SKIPPED
    connect(tmp_path / WAREHOUSE_FILE).close()
    result = narrate(ctx(tmp_path), client_factory=FakeClient)
    assert result.status is StageStatus.SKIPPED
    assert "mart_weekly_report not built yet" in (result.message or "")


# ── Live ────────────────────────────────────────────────────────────────────


@pytest.mark.live
@pytest.mark.skipif(not LIVE_KEY, reason="ANTHROPIC_API_KEY not set")
def test_live_call_returns_a_grounded_narrative(report: list[WeeklyReport], tmp_path: Path) -> None:
    client = AnthropicClient.from_env({"ANTHROPIC_API_KEY": LIVE_KEY, **os.environ})
    assert client is not None
    outcome = narrate_node(build_facts(report, "ON", WEEK), client, ResponseCache(tmp_path))
    assert not outcome.narrative.fallback, outcome.reason


def test_the_lead_kpi_heads_the_narrative_once_it_has_a_value(
    report: list[WeeklyReport],
) -> None:
    # With 12 months behind the week, portfolio contacted leads; activities moves to a bullet.
    filled = [
        r.model_copy(update={"value": 0.83, "prior_week_value": 0.85, "wow_pct": -0.0235})
        if r.kpi_code is KpiCode.PRTF_CONTACT_12M and r.iso_week_id == WEEK
        else r
        for r in report
    ]
    node = build_facts(filled, "GTA", WEEK)
    assert node.headline_kpi is KpiCode.PRTF_CONTACT_12M
    narrative = template_narrative(node)
    assert narrative.headline.startswith("GTA: portfolio contacted (12 months) fell 2.4%")
    assert "83.0%" in narrative.headline
    assert any(b.text.startswith("Activities per advisor") for b in narrative.bullets)
    assert "Headline KPI: Portfolio contacted (12 months)" in user_message(node)
