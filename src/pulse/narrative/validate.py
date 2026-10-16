"""Numeric-claim and phrase guardrails for a narrative (PLAN.md §11).

Every number in the text must match a fact it cites, within the rounding the text shows:
"3.4%" matches a wow_pct of 0.0337, "10.4" matches 10.44. The headline cites nothing, so
it may use any of the node's facts. A direction word ("rose", "fell") before a week-over-week
number must agree with that fact's sign. Banned phrases cover live/real-time wording, advice,
and speculation about causes or individuals.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pulse.contracts.exports import NarrativeFact, NodeNarrative
from pulse.narrative.prompt import RATE_KPIS

# Tokens that contain digits but are names, not claims: ISO weeks, branch and fact IDs,
# advisor IDs, and the "13-week" / "12 weeks" window wording.
_NOT_CLAIMS = re.compile(
    r"\b\d{4}-W\d{2}\b|\b[A-Z]{2,}-\d+\b|\bF\d+\b|\b1[23][- ]weeks?\b|\b1[23]w\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?)(\s?%| percentage points?| pp\b)?")
_UP = re.compile(
    r"\b(rose|rise|rises|up|increased?|increases|grew|grows|gained?|higher|climbed?)\b"
)
_DOWN = re.compile(
    r"\b(fell|falls?|down|decreased?|decreases|dropped|drops?|declined?|declines|lower|slipped)\b"
)

BANNED: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("live wording", re.compile(r"\blive\b|\breal[- ]time\b", re.IGNORECASE)),
    (
        "advice",
        re.compile(
            r"\b(should|must|recommend\w*|we suggest|consider (?:adding|hiring|coaching)|"
            r"needs? to)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "speculation",
        re.compile(
            r"\b(because|due to|likely|probably|perhaps|presumably|caused by|driven by|"
            r"suggests that|lazy|underperform\w* advisor)\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class Problem:
    kind: str  # fabricated | uncited | wrong_sign | banned
    where: str  # headline | bullet 1 | watchlist 1
    detail: str

    def __str__(self) -> str:
        return f"{self.where}: {self.kind}: {self.detail}"


@dataclass(frozen=True)
class _Candidate:
    value: float
    fact_id: str
    sign: int = 0  # for week-over-week candidates: the direction the fact moved


def _sign(x: float | None) -> int:
    return 0 if x is None or abs(x) < 1e-12 else (1 if x > 0 else -1)


def _candidates(fact: NarrativeFact, percent: bool) -> list[_Candidate]:
    rate = fact.kpi_code in RATE_KPIS
    out: list[_Candidate] = []
    levels = [fact.value, fact.prior_week_value, fact.trailing_13w_avg]
    delta = (
        None
        if fact.value is None or fact.prior_week_value is None
        else fact.value - fact.prior_week_value
    )
    if percent:
        if fact.wow_pct is not None:
            out.append(_Candidate(abs(fact.wow_pct) * 100, fact.fact_id, _sign(fact.wow_pct)))
        if rate:
            out += [_Candidate(v * 100, fact.fact_id) for v in levels if v is not None]
            if delta is not None:  # percentage points
                out.append(_Candidate(abs(delta) * 100, fact.fact_id, _sign(delta)))
    else:
        if not rate:
            out += [_Candidate(v, fact.fact_id) for v in levels if v is not None]
            if delta is not None:
                out.append(_Candidate(abs(delta), fact.fact_id, _sign(delta)))
        out += [
            _Candidate(float(v), fact.fact_id)
            for v in (fact.rank_in_parent, fact.peer_count)
            if v is not None
        ]
    return out


def _matches(number: float, decimals: int, candidate: float) -> bool:
    tolerance = 0.5 * 10**-decimals + 1e-9
    return (
        math.isclose(number, candidate, abs_tol=tolerance) or abs(number - candidate) <= tolerance
    )


def check_text(
    text: str, where: str, cited: Sequence[NarrativeFact], all_facts: Sequence[NarrativeFact]
) -> list[Problem]:
    problems: list[Problem] = []
    for label, pattern in BANNED:
        if found := pattern.search(text):
            problems.append(Problem("banned", where, f'{label}: "{found.group(0)}"'))

    cleaned = _NOT_CLAIMS.sub(lambda m: " " * len(m.group(0)), text)
    previous_end = 0
    for match in _NUMBER.finditer(cleaned):
        raw, unit = match.group(1), match.group(2)
        number = float(raw.replace(",", ""))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        percent = unit is not None
        shown = match.group(0).strip()
        clause = cleaned[previous_end : match.start()].lower()
        previous_end = match.end()

        hits = [
            c for f in cited for c in _candidates(f, percent) if _matches(number, decimals, c.value)
        ]
        if not hits:
            elsewhere = [
                c.fact_id
                for f in all_facts
                if f not in cited
                for c in _candidates(f, percent)
                if _matches(number, decimals, c.value)
            ]
            if elsewhere:
                problems.append(
                    Problem("uncited", where, f"{shown} matches {elsewhere[0]}, which is not cited")
                )
            else:
                problems.append(Problem("fabricated", where, f"{shown} matches no cited fact"))
            continue

        says = _said_direction(clause)
        directional = [c for c in hits if c.sign != 0]
        if (
            says
            and directional
            and len(directional) == len(hits)
            and all(c.sign != says for c in directional)
        ):
            word = "a rise" if says > 0 else "a fall"
            fact_id = directional[0].fact_id
            problems.append(
                Problem(
                    "wrong_sign", where, f"says {word} at {shown}; {fact_id} moved the other way"
                )
            )
    return problems


def _said_direction(clause: str) -> int:
    """The last direction word before the number: +1 up, -1 down, 0 none."""
    ups = [m.end() for m in _UP.finditer(clause)]
    downs = [m.end() for m in _DOWN.finditer(clause)]
    if not ups and not downs:
        return 0
    return 1 if max(ups, default=-1) > max(downs, default=-1) else -1


def validate(
    narrative: NodeNarrative, facts: Iterable[NarrativeFact] | None = None
) -> list[Problem]:
    """Every problem in the headline, bullets and watchlist reasons; empty means it passes."""
    all_facts = list(facts if facts is not None else narrative.facts_used)
    by_id = {f.fact_id: f for f in all_facts}

    def cited(ids: Sequence[str]) -> list[NarrativeFact]:
        return [by_id[i] for i in ids if i in by_id]

    problems = check_text(narrative.headline, "headline", all_facts, all_facts)
    for i, bullet in enumerate(narrative.bullets, 1):
        problems += check_text(bullet.text, f"bullet {i}", cited(bullet.fact_ids), all_facts)
    for i, item in enumerate(narrative.watchlist, 1):
        problems += check_text(item.reason, f"watchlist {i}", cited(item.fact_ids), all_facts)
    return problems
