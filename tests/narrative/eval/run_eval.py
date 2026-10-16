"""Narrative eval: 10 frozen fact sets, checked for the properties a weekly narrative needs.

    uv run python tests/narrative/eval/run_eval.py            # offline: recorded answers
    uv run python tests/narrative/eval/run_eval.py --live     # call the model (needs key)
    uv run python tests/narrative/eval/run_eval.py --live --record   # and save the answers
    uv run python tests/narrative/eval/run_eval.py --freeze   # rebuild cases.json

Properties per case: the answer fits the contract and cites only known facts (``contract``),
every number matches a cited fact with the right sign (``grounded``), no banned phrase
(``phrases``), and the headline's direction agrees with the headline KPI (``direction``).
The live mode scores the model's *first* answer, before any regeneration.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pulse.contracts.enums import OrgLevel
from pulse.contracts.exports import NarrativeFact, WeeklyReport
from pulse.narrative.facts import HEADLINE_KPI, NodeFacts, build_facts, narrated_nodes
from pulse.narrative.generate import UnusableResponse, to_narrative
from pulse.narrative.prompt import user_message
from pulse.narrative.validate import validate

HERE = Path(__file__).parent
CASES = HERE / "cases.json"
RECORDED = HERE / "recorded"
WEEKS = ("2026-W39", "2026-W40")
PROPERTIES = ("contract", "grounded", "phrases", "direction")
_UP = ("rose", "up ", "increase", "grew", "higher", "climbed")
_DOWN = ("fell", "down ", "decrease", "dropped", "declined", "lower")


@dataclass(frozen=True)
class Case:
    case_id: str
    node: NodeFacts
    direction: str  # up | down | flat, from the headline KPI's wow_pct


def _direction(node: NodeFacts) -> str:
    lead = next(
        (f for f in node.facts if f.node_id == node.node_id and f.kpi_code is HEADLINE_KPI),
        None,
    )
    pct = lead.wow_pct if lead else None
    if pct is None or abs(pct) < 0.01:
        return "flat"
    return "up" if pct > 0 else "down"


def freeze(report_parquet: Path) -> None:
    import pyarrow.parquet as pq

    report = [WeeklyReport.model_validate(r) for r in pq.read_table(report_parquet).to_pylist()]
    cases = []
    for week in WEEKS:
        for node_id, _ in narrated_nodes(report, week):
            node = build_facts(report, node_id, week)
            cases.append(
                {
                    "case_id": f"{week}-{node_id}",
                    "node_id": node.node_id,
                    "node_name": node.node_name,
                    "level": node.level.value,
                    "iso_week_id": week,
                    "children": node.children,
                    "direction": _direction(node),
                    "facts": [f.model_dump(mode="json") for f in node.facts],
                }
            )
    CASES.write_text(json.dumps(cases, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Froze {len(cases)} cases into {CASES}")


def load_cases() -> list[Case]:
    out = []
    for c in json.loads(CASES.read_text(encoding="utf-8")):
        node = NodeFacts(
            node_id=c["node_id"],
            node_name=c["node_name"],
            level=OrgLevel(c["level"]),
            iso_week_id=c["iso_week_id"],
            children=dict(c["children"]),
            facts=tuple(NarrativeFact.model_validate(f) for f in c["facts"]),
        )
        out.append(Case(c["case_id"], node, c["direction"]))
    return out


def score(case: Case, answer: dict[str, Any], model: str = "recorded") -> dict[str, bool]:
    """Pass/fail per property for one answer."""
    try:
        narrative = to_narrative(case.node, answer, model)
    except UnusableResponse:
        return dict.fromkeys(PROPERTIES, False)
    problems = validate(narrative, case.node.facts)
    headline = narrative.headline.lower()
    said_up, said_down = any(w in headline for w in _UP), any(w in headline for w in _DOWN)
    direction = {
        "up": not said_down,
        "down": not said_up,
        "flat": not (said_up or said_down) or "held" in headline,
    }[case.direction]
    return {
        "contract": True,
        "grounded": not any(p.kind != "banned" for p in problems),
        "phrases": not any(p.kind == "banned" for p in problems),
        "direction": direction,
    }


def recorded(case_id: str) -> dict[str, Any]:
    doc = json.loads((RECORDED / f"{case_id}.json").read_text(encoding="utf-8"))
    answer: dict[str, Any] = doc["answer"]
    return answer


def table(rows: list[tuple[str, dict[str, bool]]]) -> str:
    width = max(len(r[0]) for r in rows)
    head = f"{'case':<{width}}  " + "  ".join(f"{p:<9}" for p in PROPERTIES) + "  pass"
    lines = [head, "-" * len(head)]
    for case_id, result in rows:
        marks = "  ".join(f"{'ok' if result[p] else 'FAIL':<9}" for p in PROPERTIES)
        lines.append(f"{case_id:<{width}}  {marks}  {'yes' if all(result.values()) else 'no'}")
    n = len(rows)
    rates = "  ".join(f"{sum(r[1][p] for r in rows) / n:<9.0%}" for p in PROPERTIES)
    passed = sum(all(r[1].values()) for r in rows)
    lines += ["-" * len(head), f"{'pass rate':<{width}}  {rates}  {passed}/{n}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--live", action="store_true", help="call the model instead of recordings")
    parser.add_argument("--record", action="store_true", help="with --live: save the answers")
    parser.add_argument("--freeze", action="store_true", help="rebuild cases.json from fixtures")
    args = parser.parse_args(argv)

    if args.freeze:
        freeze(HERE.parents[2] / "fixtures" / "exports" / "weekly_report.parquet")
        return 0

    rows: list[tuple[str, dict[str, bool]]] = []
    if args.live:
        from pulse.narrative.client import AnthropicClient

        client = AnthropicClient.from_env()
        if client is None:
            print("ANTHROPIC_API_KEY is not set; the live eval needs it.", file=sys.stderr)
            return 2
        for case in load_cases():
            answer = client.complete(user_message(case.node))
            rows.append((case.case_id, score(case, answer, client.model)))
            if args.record:
                RECORDED.mkdir(exist_ok=True)
                doc = {"source": "model", "model": client.model, "answer": answer}
                (RECORDED / f"{case.case_id}.json").write_text(
                    json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8"
                )
        print(f"Live eval, model {client.model}, first answers only:\n")
    else:
        rows = [(c.case_id, score(c, recorded(c.case_id))) for c in load_cases()]
        print("Offline eval on recorded answers:\n")
    print(table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
