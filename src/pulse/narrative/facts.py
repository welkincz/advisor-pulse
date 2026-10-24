"""Compact, numbered facts (F1, F2, ...) for one node's weekly narrative (PLAN.md §11).

Order is fixed so the same report always yields the same facts, and so the same cache key:
the node's KPIs this week, then each child's core KPIs, then the node's 13-week history of
the headline KPI. The headline is the lead KPI, portfolio contacted (12 months); a week
without a full 12-month window has no value for it, so activities per advisor leads instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from pulse.contracts.enums import KpiCode, OrgLevel
from pulse.contracts.exports import NarrativeFact, WeeklyReport

HEADLINE_KPI = KpiCode.PRTF_CONTACT_12M
FALLBACK_HEADLINE_KPI = KpiCode.ACT_PER_ADV
CHILD_KPIS = (
    KpiCode.PRTF_CONTACT_12M,
    KpiCode.ACT_PER_ADV,
    KpiCode.SHOW_RATE,
    KpiCode.APPT_CONV,
)
HISTORY_WEEKS = 13
NARRATED_LEVELS = (OrgLevel.REGION, OrgLevel.DISTRICT)
DIGITS = 4


@dataclass(frozen=True)
class NodeFacts:
    node_id: str
    node_name: str
    level: OrgLevel
    iso_week_id: str
    children: dict[str, str]  # child node_id -> name
    facts: tuple[NarrativeFact, ...]
    headline_kpi: KpiCode = HEADLINE_KPI

    def by_id(self) -> dict[str, NarrativeFact]:
        return {f.fact_id: f for f in self.facts}


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, DIGITS)


def weeks_back(week: str, n: int) -> list[str]:
    """The ``n`` weeks before ``week``, oldest first."""
    monday = date.fromisoformat(f"{week}-1")
    out = []
    for back in range(n, 0, -1):
        y, w, _ = (monday - timedelta(weeks=back)).isocalendar()
        out.append(f"{y}-W{w:02d}")
    return out


def narrated_nodes(report: Sequence[WeeklyReport], week: str) -> list[tuple[str, OrgLevel]]:
    """Regions then districts reported in ``week``, each sorted by node_id."""
    nodes = {(r.node_id, r.level) for r in report if r.iso_week_id == week}
    return sorted(
        (n for n in nodes if n[1] in NARRATED_LEVELS),
        key=lambda n: (NARRATED_LEVELS.index(n[1]), n[0]),
    )


def build_facts(report: Sequence[WeeklyReport], node_id: str, week: str) -> NodeFacts:
    rows = {(r.iso_week_id, r.node_id, r.kpi_code): r for r in report}
    current = [r for r in report if r.iso_week_id == week]
    node = next((r for r in current if r.node_id == node_id), None)
    if node is None:
        raise ValueError(f"{node_id} has no weekly_report rows for {week}")
    children = {r.node_id: r.node_name for r in current if r.parent_id == node_id}

    facts: list[NarrativeFact] = []

    def add(row: WeeklyReport | None) -> None:
        if row is None or row.value is None:
            return
        facts.append(
            NarrativeFact(
                fact_id=f"F{len(facts) + 1}",
                node_id=row.node_id,
                kpi_code=row.kpi_code,
                iso_week_id=row.iso_week_id,
                value=_round(row.value),
                prior_week_value=_round(row.prior_week_value),
                wow_pct=row.wow_pct,  # unrounded, as stored: the change the site shows (#310)
                trailing_13w_avg=_round(row.trailing_13w_avg),
                rank_in_parent=row.rank_in_parent,
                peer_count=row.peer_count,
            )
        )

    for kpi in KpiCode:
        add(rows.get((week, node_id, kpi)))
    for child in sorted(children):
        for kpi in CHILD_KPIS:
            add(rows.get((week, child, kpi)))
    lead = rows.get((week, node_id, HEADLINE_KPI))
    headline = (
        HEADLINE_KPI if lead is not None and lead.value is not None else FALLBACK_HEADLINE_KPI
    )
    for past in weeks_back(week, HISTORY_WEEKS - 1):
        add(rows.get((past, node_id, headline)))

    if not facts:
        raise ValueError(f"{node_id} has no non-null KPI values for {week}")
    return NodeFacts(node_id, node.node_name, node.level, week, children, tuple(facts), headline)
