"""Unit tests for scripts/deps_bot.py (parser + decision helpers)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deps_bot.py"


def _load_deps_bot() -> Any:
    spec = importlib.util.spec_from_file_location("deps_bot", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deps_bot = _load_deps_bot()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Depends on: none\n", frozenset()),
        ("Depends on: None\n", frozenset()),
        ("Depends on: NONE\n", frozenset()),
        ("Depends on: #3\n", frozenset({3})),
        ("Depends on: #3, #12\n", frozenset({3, 12})),
        ("Depends on:  #3 ,  #12  \n", frozenset({3, 12})),
        ("Depends on:#3,#12\n", frozenset({3, 12})),
        ("Intro\n\nDepends on: #3, #12\n\n## More\n", frozenset({3, 12})),
        ("No depends line here", None),
        (None, None),
        ("", None),
    ],
)
def test_parse_depends_on(body: str | None, expected: frozenset[int] | None) -> None:
    assert deps_bot.parse_depends_on(body) == expected


@pytest.mark.unit
def test_parse_depends_on_none_with_extra_whitespace() -> None:
    assert deps_bot.parse_depends_on("Depends on:   none   \n") == frozenset()


@pytest.mark.unit
def test_should_process_skips_in_progress() -> None:
    issue = {
        "state": "open",
        "labels": [{"name": "status:blocked"}, {"name": "status:in-progress"}],
    }
    assert deps_bot.should_process(issue) is False


@pytest.mark.unit
def test_should_process_requires_blocked() -> None:
    issue = {"state": "open", "labels": [{"name": "status:ready"}]}
    assert deps_bot.should_process(issue) is False


@pytest.mark.unit
def test_should_process_accepts_blocked_open() -> None:
    issue = {"state": "open", "labels": [{"name": "status:blocked"}]}
    assert deps_bot.should_process(issue) is True


@pytest.mark.unit
def test_should_process_skips_pull_requests() -> None:
    issue = {
        "state": "open",
        "labels": [{"name": "status:blocked"}],
        "pull_request": {},
    }
    assert deps_bot.should_process(issue) is False


@pytest.mark.unit
def test_deps_satisfied_empty_and_closed() -> None:
    assert deps_bot.deps_satisfied(frozenset(), {}) is True
    assert deps_bot.deps_satisfied(frozenset({3, 12}), {3: "closed", 12: "closed"}) is True
    assert deps_bot.deps_satisfied(frozenset({3, 12}), {3: "closed", 12: "open"}) is False
    assert deps_bot.deps_satisfied(frozenset({3}), {3: None}) is False


@pytest.mark.unit
def test_has_ready_comment_idempotent_marker() -> None:
    assert deps_bot.has_ready_comment([{"body": "hello"}]) is False
    assert deps_bot.has_ready_comment([{"body": f"x\n{deps_bot.READY_COMMENT_MARKER}\n"}]) is True


class _FakeClient:
    def __init__(self) -> None:
        self.removed: list[tuple[int, str]] = []
        self.added: list[tuple[int, list[str]]] = []
        self.comments_posted: list[tuple[int, str]] = []
        self._comments: dict[int, list[dict[str, str]]] = {}

    def list_comments(self, number: int) -> list[dict[str, str]]:
        return list(self._comments.get(number, []))

    def remove_label(self, number: int, label: str) -> None:
        self.removed.append((number, label))

    def add_labels(self, number: int, labels: list[str]) -> None:
        self.added.append((number, labels))

    def create_comment(self, number: int, body: str) -> None:
        self.comments_posted.append((number, body))
        self._comments.setdefault(number, []).append({"body": body})


@pytest.mark.unit
def test_unblock_issue_swaps_labels_and_comments_once() -> None:
    client = _FakeClient()
    issue = {
        "number": 42,
        "labels": [{"name": "status:blocked"}, {"name": "area:infra"}],
    }
    assert deps_bot.unblock_issue(client, issue) is True
    assert client.removed == [(42, "status:blocked")]
    assert client.added == [(42, ["status:ready"])]
    assert len(client.comments_posted) == 1
    assert deps_bot.READY_COMMENT_MARKER in client.comments_posted[0][1]

    # Idempotent re-run: labels already swapped; comment marker present.
    issue_after = {
        "number": 42,
        "labels": [{"name": "status:ready"}, {"name": "area:infra"}],
    }
    client._comments[42] = [{"body": client.comments_posted[0][1]}]
    assert deps_bot.unblock_issue(client, issue_after) is False
    assert len(client.comments_posted) == 1
