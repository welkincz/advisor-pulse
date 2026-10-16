"""The model call behind the narrative, as a small protocol so tests use a recorded fake."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from pulse.narrative.prompt import DEFAULT_MODEL, MAX_TOKENS, RESPONSE_SCHEMA, SYSTEM

MODEL_ENV = "PULSE_NARRATIVE_MODEL"
KEY_ENV = "ANTHROPIC_API_KEY"
BACKEND_ENV = "PULSE_NARRATIVE_BACKEND"
CLAUDE_CODE = "claude-code"
# The Pro subscription has the tighter Opus limit; Sonnet keeps a weekly run well inside it.
CLAUDE_CODE_MODEL = "claude-sonnet-5-5"
CLI_TIMEOUT = 300.0


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


Run = Callable[..., subprocess.CompletedProcess[str]]


class ClaudeCodeClient:
    """``claude -p`` with ``--json-schema``: runs on the Claude subscription, not API billing.

    Locally the CLI uses the logged-in account; in CI it reads ``CLAUDE_CODE_OAUTH_TOKEN``
    (from ``claude setup-token``). ``ANTHROPIC_API_KEY`` is removed from the CLI's
    environment, because the CLI would otherwise bill that key.
    """

    def __init__(
        self,
        binary: str,
        model: str = CLAUDE_CODE_MODEL,
        env: Mapping[str, str] = os.environ,
        run: Run = subprocess.run,
    ) -> None:
        self.model = model
        self._binary = binary
        self._env = {k: v for k, v in env.items() if k != KEY_ENV}
        self._run = run

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> ClaudeCodeClient | None:
        """None when the ``claude`` CLI is not on PATH."""
        binary = shutil.which("claude", path=env.get("PATH"))
        if binary is None:
            return None
        return cls(binary, env.get(MODEL_ENV, "").strip() or CLAUDE_CODE_MODEL, env)

    def args(self) -> Sequence[str]:
        return [
            self._binary,
            "--print",
            "--output-format",
            "json",
            "--model",
            self.model,
            "--system-prompt",
            SYSTEM,
            "--json-schema",
            json.dumps(RESPONSE_SCHEMA),
            # A plain completion: no tools, MCP servers, settings or saved session.
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--no-session-persistence",
        ]

    def complete(self, user: str) -> dict[str, Any]:
        # An empty working directory, so no project CLAUDE.md is added to the prompt.
        with tempfile.TemporaryDirectory() as cwd:
            proc = self._run(
                self.args(),
                input=user,
                capture_output=True,
                text=True,
                timeout=CLI_TIMEOUT,
                cwd=cwd,
                env=self._env,
                check=False,
            )
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            detail = (proc.stderr or proc.stdout).strip()[:200]
            raise ValueError(f"claude CLI exited {proc.returncode}: {detail}") from None
        if result.get("is_error") or proc.returncode != 0:
            detail = str(result.get("result") or result.get("subtype"))[:200]
            raise ValueError(f"claude CLI failed: {detail}")
        parsed = result.get("structured_output")
        if not isinstance(parsed, dict):
            raise ValueError("claude CLI returned no structured output.")
        return parsed


def client_from_env(env: Mapping[str, str] = os.environ) -> NarrativeClient | None:
    """The backend named by PULSE_NARRATIVE_BACKEND (``api`` by default), or None.

    None means no way to call a model, and the stage writes template narratives.
    """
    backend = env.get(BACKEND_ENV, "").strip() or "api"
    if backend == CLAUDE_CODE:
        return ClaudeCodeClient.from_env(env)
    if backend == "api":
        return AnthropicClient.from_env(env)
    raise ValueError(f"{BACKEND_ENV} must be 'api' or '{CLAUDE_CODE}', not {backend!r}.")
