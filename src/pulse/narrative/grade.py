"""A deterministic grader for one model narrative: an editor's checks, not a role play.

Every rule reads only the narrative and the facts it was written from, so a score means the
same thing on every run. ``action`` names where a manager should look, not what to do, because
the guardrails in ``validate`` forbid advice (PLAN.md §11).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pulse.contracts.exports import NodeNarrative
from pulse.narrative.facts import NodeFacts
from pulse.narrative.prompt import KPI_LABELS, MAX_WATCHLIST
from pulse.narrative.validate import BANNED, validate

RULES = (
    "grounded",
    "anomalies",
    "lead_first",
    "length",
    "reading_level",
    "wording",
    "one_claim",
    "no_cause",
    "action",
)
MAX_HEADLINE_CHARS = 120
BULLETS = range(2, 6)
MAX_BULLET_WORDS = 40
MAX_READING_GRADE = 12.0
MAX_KPIS_PER_BULLET = 2
# Below this share of graded narratives passing, the narrate stage warns.
PASS_FLOOR = 0.8

_HYPE = re.compile(
    r"\b(amazing|astonishing|dramatic(?:ally)?|exceptional(?:ly)?|impressive(?:ly)?|incredible|"
    r"outstanding|phenomenal|remarkabl[ey]|skyrocket\w*|soar\w*|stellar|stunning|surg\w*)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.!?;](?=\s|$)")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_VOWELS = re.compile(r"[aeiouy]+")


@dataclass(frozen=True)
class Grade:
    node_id: str
    failed: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failed


def _sentences(text: str) -> int:
    return max(1, len(_SENTENCE_END.findall(text.strip())))


def _syllables(word: str) -> int:
    word = word.lower()
    count = len(_VOWELS.findall(word))
    if word.endswith("e") and not word.endswith("le") and count > 1:
        count -= 1
    return max(1, count)


def reading_grade(text: str) -> float:
    """Flesch-Kincaid grade of the words; figures are not read as words."""
    words = _WORD.findall(text)
    if not words:
        return 0.0
    syllables = sum(_syllables(w) for w in words)
    return 0.39 * len(words) / _sentences(text) + 11.8 * syllables / len(words) - 15.59


def _cited(narrative: NodeNarrative) -> set[str]:
    bullets = {f for bullet in narrative.bullets for f in bullet.fact_ids}
    return bullets | {f for watched in narrative.watchlist for f in watched.fact_ids}


def _lead_first(narrative: NodeNarrative, node: NodeFacts) -> bool:
    lead = next(
        (
            f.fact_id
            for f in node.facts
            if f.node_id == node.node_id
            and f.iso_week_id == node.iso_week_id
            and f.kpi_code is node.headline_kpi
        ),
        None,
    )
    if lead is None:
        return True
    label = KPI_LABELS[node.headline_kpi].lower().split(" (")[0]
    return label in narrative.headline.lower() and lead in narrative.bullets[0].fact_ids


def _one_claim(narrative: NodeNarrative, node: NodeFacts) -> bool:
    by_id = node.by_id()
    for bullet in narrative.bullets:
        kpis = {by_id[f].kpi_code for f in bullet.fact_ids if f in by_id}
        if _sentences(bullet.text) > 1 or len(kpis) > MAX_KPIS_PER_BULLET:
            return False
    return True


def _action(narrative: NodeNarrative, node: NodeFacts) -> bool:
    """Children flagged this week are on the watchlist, so the reader knows where to look.

    The prompt caps the watchlist at ``MAX_WATCHLIST``, so the rule asks for
    ``min(len(flagged), MAX_WATCHLIST)`` flagged children on it, not all of them. The prompt
    names no order among flagged children, so when there are more than the cap any of them
    count: requiring a particular few would fail answers that follow every stated rule.
    """
    by_id = node.by_id()
    flagged = {by_id[f].node_id for f in node.anomalies if f in by_id} & set(node.children)
    watched = flagged & {w.node_id for w in narrative.watchlist}
    return len(watched) >= min(len(flagged), MAX_WATCHLIST)


def grade(narrative: NodeNarrative, node: NodeFacts) -> Grade:
    problems = validate(narrative, node.facts)
    text = " ".join(
        [
            narrative.headline,
            *(b.text for b in narrative.bullets),
            *(w.reason for w in narrative.watchlist),
        ]
    )
    speculation = dict(BANNED)["speculation"]
    results = {
        "grounded": not any(p.kind != "banned" for p in problems),
        "anomalies": set(node.anomalies) <= _cited(narrative),
        "lead_first": _lead_first(narrative, node),
        "length": len(narrative.headline) <= MAX_HEADLINE_CHARS
        and len(narrative.bullets) in BULLETS
        and all(len(b.text.split()) <= MAX_BULLET_WORDS for b in narrative.bullets),
        "reading_level": reading_grade(text) <= MAX_READING_GRADE,
        "wording": not _HYPE.search(text)
        and not any(pattern.search(text) for name, pattern in BANNED if name == "live wording"),
        "one_claim": _one_claim(narrative, node),
        "no_cause": not speculation.search(text),
        "action": _action(narrative, node),
    }
    return Grade(narrative.node_id, tuple(rule for rule in RULES if not results[rule]))


def summarize(grades: Sequence[Grade]) -> str:
    """The sentence the run log carries. The quality page reads it (features/quality/checks.ts)."""
    passed = sum(g.passed for g in grades)
    return f"Grader: {passed} of {len(grades)} narratives pass."


def below_floor(grades: Iterable[Grade]) -> bool:
    grades = list(grades)
    return bool(grades) and sum(g.passed for g in grades) / len(grades) < PASS_FLOOR
