"""Guarded generation: model answer → validate → one regeneration with feedback → template.

The template is grounded by construction, so every node always gets a narrative, even when
the API is down or both answers fail the validator.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pulse.contracts.exports import NodeNarrative
from pulse.narrative.client import NarrativeClient
from pulse.narrative.facts import NodeFacts
from pulse.narrative.generate import UnusableResponse, to_narrative
from pulse.narrative.prompt import user_message
from pulse.narrative.template import template_narrative
from pulse.narrative.validate import Problem, validate

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # the first answer plus one regeneration


@dataclass(frozen=True)
class Guarded:
    narrative: NodeNarrative
    response: dict[str, Any] | None  # the accepted model answer, to cache; None for templates
    attempts: int
    reason: str | None = None  # why the template was used, if it was


def feedback_message(node: NodeFacts, answer: dict[str, Any], problems: Sequence[str]) -> str:
    lines = "\n".join(f"- {p}" for p in problems)
    return (
        f"{user_message(node)}\n\nYour previous answer failed validation:\n{lines}\n\n"
        f"Previous answer:\n{json.dumps(answer, separators=(',', ':'))}\n\n"
        "Answer again. Use only numbers from the facts each sentence cites, and fix every "
        "problem listed."
    )


def check(
    node: NodeFacts, answer: dict[str, Any], model: str
) -> tuple[NodeNarrative | None, list[str]]:
    """The narrative if the answer passes every check, else the problems found."""
    try:
        narrative = to_narrative(node, answer, model)
    except UnusableResponse as exc:
        return None, [str(exc)]
    problems: list[Problem] = validate(narrative, node.facts)
    if problems:
        return None, [str(p) for p in problems]
    return narrative, []


def generate_guarded(
    node: NodeFacts, client: NarrativeClient, first: dict[str, Any] | None = None
) -> Guarded:
    """``first`` is a cached answer to re-check before spending a call."""
    answer = first
    prior: dict[str, Any] = {}
    problems: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if answer is None:
            message = (
                user_message(node) if not problems else feedback_message(node, prior, problems)
            )
            try:
                answer = client.complete(message)
            except Exception as exc:  # API outage must not block the weekly report
                log.warning("Narrative for %s fell back: %s", node.node_id, exc)
                return Guarded(
                    template_narrative(node), None, attempt, f"API error: {type(exc).__name__}"
                )
        narrative, problems = check(node, answer, client.model)
        if narrative is not None:
            return Guarded(narrative, answer, attempt)
        log.warning("Narrative for %s failed validation: %s", node.node_id, "; ".join(problems))
        prior, answer = answer, None
    return Guarded(
        template_narrative(node), None, MAX_ATTEMPTS, f"failed validation: {problems[0]}"
    )
