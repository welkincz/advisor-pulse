"""The narrative writes numbers exactly as the site does (#310)."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from pulse.contracts.enums import KpiCode
from pulse.contracts.exports import WeeklyReport
from pulse.narrative.facts import build_facts
from pulse.narrative.prompt import fmt, fmt_share
from pulse.narrative.template import template_narrative

ROOT = Path(__file__).parents[2]
CASES = json.loads(
    (Path(__file__).parents[2] / "web" / "src" / "data" / "format-cases.json").read_text()
)


@pytest.mark.parametrize("case", CASES["kpi"], ids=lambda c: f"{c['code']}-{c['value']}")
def test_fmt_matches_the_site(case: dict[str, object]) -> None:
    assert fmt(KpiCode(case["code"]), float(case["value"])) == case["text"]  # type: ignore[arg-type]


@pytest.mark.parametrize("case", CASES["change"], ids=lambda c: str(c["share"]))
def test_fmt_share_matches_the_site(case: dict[str, object]) -> None:
    """The size of a change, as the site writes it after its sign."""
    assert fmt_share(float(case["share"])) == str(case["text"])[1:]  # type: ignore[arg-type]


def test_template_writes_the_unrounded_change() -> None:
    """A change of 12.05...% rounds to 12.0% at four places but shows as +12.1% on the site."""
    rows = [
        WeeklyReport.model_validate(r)
        for r in pq.read_table(ROOT / "fixtures" / "exports" / "weekly_report.parquet").to_pylist()
    ]
    week = max(r.iso_week_id for r in rows)
    lead = next(r for r in rows if r.iso_week_id == week and r.level.value == "REGION")
    kpi = build_facts(rows, lead.node_id, week).headline_kpi
    target = next(
        r for r in rows if (r.iso_week_id, r.node_id, r.kpi_code) == (week, lead.node_id, kpi)
    )
    changed = target.model_copy(update={"wow_pct": 0.0094 / 0.078})  # 0.120512...
    rows = [changed if r is target else r for r in rows]

    facts = build_facts(rows, lead.node_id, week)
    fact = next(f for f in facts.facts if f.node_id == lead.node_id and f.kpi_code is kpi)
    assert fact.wow_pct == 0.0094 / 0.078
    assert "rose 12.1% week over week" in template_narrative(facts).headline
