"""Pinned prompt, response schema and KPI wording for the weekly narrative.

Changing any text here changes the output: bump PROMPT_VERSION so cached narratives are
not reused under the new prompt.
"""

from __future__ import annotations

import json
from typing import Any

from pulse.contracts.enums import KpiCode
from pulse.narrative.facts import NodeFacts

PROMPT_VERSION = "narrative-v1"
DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 1500

KPI_LABELS: dict[KpiCode, str] = {
    KpiCode.ACT_PER_ADV: "Activities per advisor",
    KpiCode.CALLS_OUT: "Outbound calls",
    KpiCode.APPT_BOOKED: "Appointments booked",
    KpiCode.CALL_TO_APPT: "Call-to-appointment rate",
    KpiCode.SHOW_RATE: "Show rate",
    KpiCode.APPT_CONV: "Appointment conversion",
    KpiCode.CLIENTS_CONTACTED: "Clients contacted",
    KpiCode.COVERAGE_13W: "13-week coverage",
    KpiCode.AVG_MEET_MIN: "Average meeting minutes",
    KpiCode.NO_SHOW_RATE: "No-show rate",
    KpiCode.LATE_RATE: "Late-arriving rate",
    KpiCode.QUAR_RATE: "Quarantine rate",
}
RATE_KPIS = frozenset(
    {
        KpiCode.CALL_TO_APPT,
        KpiCode.SHOW_RATE,
        KpiCode.APPT_CONV,
        KpiCode.COVERAGE_13W,
        KpiCode.NO_SHOW_RATE,
        KpiCode.LATE_RATE,
        KpiCode.QUAR_RATE,
    }
)
LOWER_IS_BETTER = frozenset({KpiCode.NO_SHOW_RATE, KpiCode.LATE_RATE, KpiCode.QUAR_RATE})

SYSTEM = """\
You write the weekly activity summary for one node (region or district) of Maplecrest Bank, \
a fictional bank. The data is synthetic and comes from a weekly batch report.

Rules:
- Use only the facts given. Every number you write must come from a cited fact; round as \
the facts are rounded (rates as percentages with one decimal, other values to one decimal).
- Every bullet and watchlist item cites the fact IDs (F1, F2, ...) it uses.
- wow_pct and rate values are fractions: 0.042 means 4.2%.
- Describe what changed and how this node compares with its children or peers. Do not \
explain causes, give advice, or speculate about individual people.
- Say "weekly" or "this week", never "live" or "real-time".
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
    return (
        f"Node: {node.node_id} ({node.node_name}), level {node.level.value}, "
        f"week {node.iso_week_id}.\nChildren: {children}.\nFacts:\n{facts_json(node)}"
    )


def fmt(kpi: KpiCode, value: float) -> str:
    if kpi in RATE_KPIS:
        return f"{value:.1%}"
    return f"{value:g}" if value == int(value) else f"{value:.1f}"
