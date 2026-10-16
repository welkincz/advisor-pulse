"""One node's narrative: cache, model call, structural checks, template fallback."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pulse.contracts.exports import NarrativeBullet, NodeNarrative, WatchItem
from pulse.narrative.client import NarrativeClient
from pulse.narrative.facts import NodeFacts
from pulse.narrative.prompt import PROMPT_VERSION, facts_json, user_message
from pulse.narrative.template import template_narrative

log = logging.getLogger(__name__)


class UnusableResponse(ValueError):
    """The model answered, but the answer breaks the narrative contract or cites unknown facts."""


def cache_key(model: str, node: NodeFacts, prompt_version: str = PROMPT_VERSION) -> str:
    """sha256(prompt_version + model + facts), as PLAN.md §11 specifies."""
    return hashlib.sha256(f"{prompt_version}\n{model}\n{facts_json(node)}".encode()).hexdigest()


class ResponseCache:
    """The model's raw JSON answers by cache key, one file each. Reruns cost nothing."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None

    def put(self, key: str, response: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{key}.json"
        partial = path.with_suffix(".partial")
        partial.write_text(json.dumps(response, sort_keys=True, indent=1), encoding="utf-8")
        partial.replace(path)


def to_narrative(node: NodeFacts, response: dict[str, Any], model: str) -> NodeNarrative:
    """Check the answer against the contract and the facts it was given."""
    try:
        bullets = [NarrativeBullet.model_validate(b) for b in response.get("bullets", [])]
        watchlist = [WatchItem.model_validate(w) for w in response.get("watchlist", [])]
        narrative = NodeNarrative(
            node_id=node.node_id,
            level=node.level,
            headline=str(response.get("headline", "")).strip(),
            bullets=bullets,
            watchlist=watchlist,
            facts_used=list(node.facts),
            model=model,
            prompt_version=PROMPT_VERSION,
            validated=True,
            fallback=False,
        )
    except ValidationError as exc:
        raise UnusableResponse(f"breaks the narrative contract: {exc.errors()[0]['msg']}") from exc

    known = set(node.by_id())
    cited = {f for b in bullets for f in b.fact_ids} | {f for w in watchlist for f in w.fact_ids}
    if unknown := sorted(cited - known):
        raise UnusableResponse(f"cites unknown facts {', '.join(unknown)}")
    if strays := sorted({w.node_id for w in watchlist} - set(node.children)):
        raise UnusableResponse(f"watchlist names non-child nodes {', '.join(strays)}")
    return narrative


@dataclass(frozen=True)
class Outcome:
    narrative: NodeNarrative
    cached: bool = False
    reason: str | None = None  # why the template was used, if it was


def narrate_node(node: NodeFacts, client: NarrativeClient | None, cache: ResponseCache) -> Outcome:
    if client is None:
        return Outcome(template_narrative(node), reason="no API key")

    key = cache_key(client.model, node)
    response = cache.get(key)
    cached = response is not None
    if response is None:
        try:
            response = client.complete(user_message(node))
        except Exception as exc:  # API outage must not block the weekly report
            log.warning("Narrative for %s fell back: %s", node.node_id, exc)
            return Outcome(template_narrative(node), reason=f"API error: {type(exc).__name__}")
    try:
        narrative = to_narrative(node, response, client.model)
    except UnusableResponse as exc:
        log.warning("Narrative for %s fell back: answer %s", node.node_id, exc)
        return Outcome(template_narrative(node), cached=cached, reason=str(exc))
    if not cached:
        cache.put(key, response)  # only usable answers are cached
    return Outcome(narrative, cached=cached)
