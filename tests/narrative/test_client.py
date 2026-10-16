from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pulse.narrative.client import (
    CLAUDE_CODE_MODEL,
    AnthropicClient,
    ClaudeCodeClient,
    client_from_env,
)
from pulse.narrative.prompt import RESPONSE_SCHEMA, SYSTEM

ANSWER = {"headline": "h", "bullets": [], "watchlist": []}


class FakeRun:
    """Stands in for subprocess.run; records the call and returns a canned CLI result."""

    def __init__(self, stdout: str, returncode: int = 0, stderr: str = "") -> None:
        self.result = (stdout, returncode, stderr)
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((args, kwargs))
        stdout, code, stderr = self.result
        return subprocess.CompletedProcess(args, code, stdout, stderr)


def cli_json(**fields: Any) -> str:
    return json.dumps({"type": "result", "is_error": False, **fields})


def fake_claude(tmp_path: Path) -> str:
    binary = tmp_path / "claude"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    return str(tmp_path)


def test_passes_prompt_schema_and_isolation_flags_and_drops_the_api_key() -> None:
    run = FakeRun(cli_json(structured_output=ANSWER))
    env = {"PATH": "/bin", "ANTHROPIC_API_KEY": "sk-test", "CLAUDE_CODE_OAUTH_TOKEN": "tok"}
    client = ClaudeCodeClient("/opt/claude", env=env, run=run)

    assert client.complete("facts") == ANSWER

    args, kwargs = run.calls[0]
    assert args[:2] == ["/opt/claude", "--print"]

    def flag(name: str) -> str:
        return args[args.index(name) + 1]

    assert flag("--model") == CLAUDE_CODE_MODEL
    assert flag("--system-prompt") == SYSTEM
    assert json.loads(flag("--json-schema")) == RESPONSE_SCHEMA
    assert flag("--output-format") == "json"
    assert flag("--tools") == flag("--setting-sources") == ""
    assert {"--strict-mcp-config", "--no-session-persistence"} <= set(args)
    assert kwargs["input"] == "facts"
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert kwargs["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "tok"
    assert not Path(kwargs["cwd"]).exists()  # ran in a throwaway empty directory


def test_cli_error_result_raises_with_the_message() -> None:
    run = FakeRun(cli_json(is_error=True, result="Usage limit reached"), returncode=1)
    with pytest.raises(ValueError, match="claude CLI failed: Usage limit reached"):
        ClaudeCodeClient("/opt/claude", env={}, run=run).complete("facts")


def test_non_json_output_raises_with_stderr() -> None:
    run = FakeRun("", returncode=127, stderr="not logged in")
    with pytest.raises(ValueError, match="claude CLI exited 127: not logged in"):
        ClaudeCodeClient("/opt/claude", env={}, run=run).complete("facts")


def test_missing_structured_output_raises() -> None:
    run = FakeRun(cli_json(result="plain text"))
    with pytest.raises(ValueError, match="no structured output"):
        ClaudeCodeClient("/opt/claude", env={}, run=run).complete("facts")


def test_backend_selection(tmp_path: Path) -> None:
    assert client_from_env({}) is None
    assert isinstance(client_from_env({"ANTHROPIC_API_KEY": "sk-test"}), AnthropicClient)

    path = fake_claude(tmp_path)
    client = client_from_env({"PULSE_NARRATIVE_BACKEND": "claude-code", "PATH": path})
    assert isinstance(client, ClaudeCodeClient)
    assert client.model == CLAUDE_CODE_MODEL
    model_env = {"PULSE_NARRATIVE_BACKEND": "claude-code", "PATH": path}
    overridden = client_from_env({**model_env, "PULSE_NARRATIVE_MODEL": "claude-haiku-5-5"})
    assert overridden is not None and overridden.model == "claude-haiku-5-5"


def test_missing_cli_means_template_narratives(tmp_path: Path) -> None:
    env = {"PULSE_NARRATIVE_BACKEND": "claude-code", "PATH": str(tmp_path)}
    assert client_from_env(env) is None


def test_unknown_backend_is_a_config_error() -> None:
    with pytest.raises(ValueError, match="must be 'api' or 'claude-code'"):
        client_from_env({"PULSE_NARRATIVE_BACKEND": "openai"})
