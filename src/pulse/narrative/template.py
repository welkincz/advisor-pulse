"""Deterministic fallback narrative: used without an API key, or when the model's answer
cannot be used. Every sentence is built from one fact, so it is grounded by construction."""

from __future__ import annotations

from pulse.contracts.enums import KpiCode
from pulse.contracts.exports import NarrativeBullet, NarrativeFact, NodeNarrative, WatchItem
from pulse.narrative.facts import NodeFacts
from pulse.narrative.prompt import KPI_LABELS, LOWER_IS_BETTER, PROMPT_VERSION, fmt, fmt_share

BULLET_KPIS = (KpiCode.ACT_PER_ADV, KpiCode.CALLS_OUT, KpiCode.SHOW_RATE, KpiCode.APPT_CONV)
FLAT = 0.01  # |wow_pct| below 1% reads as "held"


def _current(node: NodeFacts, node_id: str, kpi: KpiCode) -> NarrativeFact | None:
    return next(
        (
            f
            for f in node.facts
            if f.node_id == node_id and f.kpi_code is kpi and f.iso_week_id == node.iso_week_id
        ),
        None,
    )


def _move(fact: NarrativeFact) -> str:
    value = fmt(fact.kpi_code, fact.value or 0.0)
    pct = fact.wow_pct
    if pct is None or abs(pct) < FLAT:
        return f"held at {value}"
    return f"{'rose' if pct > 0 else 'fell'} {fmt_share(pct)} week over week to {value}"


def template_narrative(node: NodeFacts) -> NodeNarrative:
    first = node.facts[0]
    lead = _current(node, node.node_id, node.headline_kpi) or first
    label = KPI_LABELS[lead.kpi_code]
    headline = f"{node.node_name}: {label[0].lower()}{label[1:]} {_move(lead)}."

    bullets: list[NarrativeBullet] = []
    for kpi in BULLET_KPIS:
        if kpi is lead.kpi_code:
            continue
        fact = _current(node, node.node_id, kpi)
        if fact is None or fact.value is None:
            continue
        text = f"{KPI_LABELS[kpi]} {fmt(kpi, fact.value)}"
        if fact.prior_week_value is not None:
            text += f", from {fmt(kpi, fact.prior_week_value)} the week before."
        else:
            text += "."
        bullets.append(NarrativeBullet(text=text, fact_ids=[fact.fact_id]))

    # The watchlist ranks children on the headline KPI, so it follows the fallback too.
    watch = node.headline_kpi
    watchlist: list[WatchItem] = []
    child_facts = [
        f
        for c in sorted(node.children)
        if (f := _current(node, c, watch)) is not None and f.value is not None
    ]
    if len(child_facts) >= 2:  # a lone child has no peers to trail
        worst = (max if watch in LOWER_IS_BETTER else min)(
            child_facts, key=lambda f: (f.value or 0.0, f.node_id)
        )
        value = fmt(watch, worst.value or 0.0)
        name = node.children[worst.node_id]
        watchlist.append(
            WatchItem(
                node_id=worst.node_id,
                reason=f"Lowest {KPI_LABELS[watch].lower()} under {node.node_name} ({value}).",
                fact_ids=[worst.fact_id],
            )
        )
        bullets.append(
            NarrativeBullet(
                text=f"{name} trails its peers on {KPI_LABELS[watch].lower()} at {value}.",
                fact_ids=[worst.fact_id],
            )
        )

    return NodeNarrative(
        node_id=node.node_id,
        level=node.level,
        headline=headline,
        bullets=bullets or [NarrativeBullet(text=headline, fact_ids=[lead.fact_id])],
        watchlist=watchlist,
        facts_used=list(node.facts),
        model=None,
        prompt_version=PROMPT_VERSION,
        validated=True,
        fallback=True,
    )
