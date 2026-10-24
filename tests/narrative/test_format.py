"""The narrative writes numbers exactly as the site does (#310)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pulse.contracts.enums import KpiCode
from pulse.narrative.prompt import fmt, fmt_change

CASES = json.loads(
    (Path(__file__).parents[2] / "web" / "src" / "data" / "format-cases.json").read_text()
)


@pytest.mark.parametrize("case", CASES["kpi"], ids=lambda c: f"{c['code']}-{c['value']}")
def test_fmt_matches_the_site(case: dict[str, object]) -> None:
    assert fmt(KpiCode(case["code"]), float(case["value"])) == case["text"]  # type: ignore[arg-type]


@pytest.mark.parametrize("case", CASES["change"], ids=lambda c: str(c["share"]))
def test_fmt_change_matches_the_site(case: dict[str, object]) -> None:
    assert fmt_change(float(case["share"])) == case["text"]  # type: ignore[arg-type]
