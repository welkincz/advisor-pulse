"""The model call behind the narrative, as a small protocol so tests use a recorded fake."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any, Protocol

from pulse.narrative.prompt import DEFAULT_MODEL, MAX_TOKENS, RESPONSE_SCHEMA, SYSTEM

MODEL_ENV = "PULSE_NARRATIVE_MODEL"
KEY_ENV = "ANTHROPIC_API_KEY"


class NarrativeClient(Protocol):
    model: str

    def complete(self, user: str) -> dict[str, Any]:
        """Return the parsed JSON object matching RESPONSE_SCHEMA."""
        ...


class AnthropicClient:
    """Anthropic Messages API with a JSON-schema structured output."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        import anthropic

        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=120.0)

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> AnthropicClient | None:
        """None without ANTHROPIC_API_KEY: the stage then writes template narratives."""
        key = env.get(KEY_ENV, "").strip()
        if not key:
            return None
        return cls(key, env.get(MODEL_ENV, "").strip() or DEFAULT_MODEL)

    def complete(self, user: str) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
        )
        if response.stop_reason == "refusal":
            raise ValueError("Model declined to write this narrative.")
        text = "".join(b.text for b in response.content if b.type == "text")
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Structured output was not a JSON object.")
        return parsed
