"""Pinned prompt, response schema and KPI wording for the weekly narrative.

Changing any text here changes the output: bump PROMPT_VERSION so cached narratives are
not reused under the new prompt.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pulse.contracts.enums import KpiCode
from pulse.narrative.facts import NodeFacts

PROMPT_VERSION = "narrative-v4"
DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 1500

KPI_LABELS: dict[KpiCode, str] = {
    KpiCode.PRTF_CONTACT_12M: "Portfolio contacted (12 months)",
    KpiCode.ACT_PER_ADV: "Activities per advisor",
    KpiCode.CALLS_OUT: "Outbound calls",
    KpiCode.APPT_BOOKED: "Appointments booked",
    KpiCode.CALL_TO_APPT: "Call-to-appointment rate",
    KpiCode.SHOW_RATE: "Show rate",
    KpiCode.APPT_CONV: "Appointment conversion",
    KpiCode.CLIENTS_CONTACTED: "Clients contacted",
    KpiCode.AVG_MEET_MIN: "Average meeting minutes",
    KpiCode.NO_SHOW_RATE: "No-show rate",
    KpiCode.LATE_RATE: "Late-arriving rate",
    KpiCode.QUAR_RATE: "Quarantine rate",
}
RATE_KPIS = frozenset(
    {
        KpiCode.PRTF_CONTACT_12M,
        KpiCode.CALL_TO_APPT,
        KpiCode.SHOW_RATE,
        KpiCode.APPT_CONV,
        KpiCode.NO_SHOW_RATE,
        KpiCode.LATE_RATE,
        KpiCode.QUAR_RATE,
    }
)
LOWER_IS_BETTER = frozenset({KpiCode.NO_SHOW_RATE, KpiCode.LATE_RATE, KpiCode.QUAR_RATE})
# Written as the site writes them (web/src/data/kpi.ts): batch rates with two decimals,
# averages with one decimal even when whole.
BATCH_RATE_KPIS = frozenset({KpiCode.LATE_RATE, KpiCode.QUAR_RATE})
AVERAGE_KPIS = frozenset({KpiCode.ACT_PER_ADV, KpiCode.AVG_MEET_MIN})

SYSTEM = """\
You write the weekly activity summary for one node (region or district) of Maplecrest Bank, \
a fictional bank. The data is synthetic and comes from a weekly batch report.

Rules:
- Use only the facts given. Every number you write must come from a cited fact.
- Write numbers exactly as the report shows them, rounding halves up: rates as percentages \
with one decimal (late-arriving and quarantine rates with two); activities per advisor and \
average meeting minutes with one decimal, even when whole (14.0); counts as whole numbers \
with thousands separators (1,284); changes as percentages with one decimal.
- Every bullet and watchlist item cites the fact IDs (F1, F2, ...) it uses.
- wow_pct and rate values are fractions: 0.042 means 4.2%.
- Describe what changed and how this node compares with its children or peers. Do not \
explain causes, give advice, or speculate about individual people.
- Say "weekly" or "this week", never "live" or "real-time".
- The headline states only the current node's headline KPI change named below. Do not \
mention or describe other KPIs in the headline; put them in bullets.
- headline: one sentence, at most 120 characters. bullets: 2 to 5. watchlist: 0 to 3 \
child nodes that trail their peers, using child node_ids from the facts."""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headline", "bullets", "watchlist"],
    "properties": {
        "headline": {"type": "string"},
        "bullets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "fact_ids"],
                "properties": {
                    "text": {"type": "string"},
                    "fact_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "watchlist": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["node_id", "reason", "fact_ids"],
                "properties": {
                    "node_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "fact_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def facts_json(node: NodeFacts) -> str:
    """The facts as compact JSON with nulls dropped; also the cache key input."""
    facts = [
        {k: v for k, v in f.model_dump(mode="json").items() if v is not None} for f in node.facts
    ]
    return json.dumps(facts, separators=(",", ":"), sort_keys=True)


def user_message(node: NodeFacts) -> str:
    children = ", ".join(f"{k} ({v})" for k, v in sorted(node.children.items())) or "none"
    headline = next(
        (
            fact
            for fact in node.facts
            if fact.node_id == node.node_id
            and fact.iso_week_id == node.iso_week_id
            and fact.kpi_code is node.headline_kpi
        ),
        None,
    )
    lead = node.headline_kpi
    focus = (
        f"Headline KPI: {KPI_LABELS[lead]} ({lead.value}, {headline.fact_id})."
        if headline is not None
        else f"Headline KPI: {lead.value} unavailable; use a neutral headline."
    )
    return (
        f"Node: {node.node_id} ({node.node_name}), level {node.level.value}, "
        f"week {node.iso_week_id}.\n{focus} Other KPIs belong in bullets, never in the headline."
        f"\nChildren: {children}.\nFacts:\n{facts_json(node)}"
    )


def _fixed(value: float, places: int) -> str:
    """JavaScript's toFixed: the exact binary value, halves rounded away from zero."""
    return f"{Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):f}"


def fmt(kpi: KpiCode, value: float) -> str:
    """A KPI value as the site writes it (formatKpi in web/src/data/kpi.ts)."""
    if kpi in RATE_KPIS:
        return f"{_fixed(value * 100, 2 if kpi in BATCH_RATE_KPIS else 1)}%"
    if kpi in AVERAGE_KPIS:
        return _fixed(value, 1)
    return f"{int(value):,}" if value == int(value) else _fixed(value, 1)


def fmt_share(share: float) -> str:
    """An unsigned change as the site writes its size (formatChange without the sign)."""
    return f"{_fixed(abs(share * 100), 1)}%"
