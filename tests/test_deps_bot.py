"""Unit tests for scripts/deps_bot.py (parser + decision helpers)."""

from __future__ import annotations

import http.client
import importlib.util
import sys
import urllib.error
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deps_bot.py"


def _load_deps_bot() -> Any:
    spec = importlib.util.spec_from_file_location("deps_bot", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses looks up the module in sys.modules during class creation
    sys.modules[spec.name] = module
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
def test_deps_satisfied_requires_completed() -> None:
    completed = deps_bot.DepStatus("closed", "completed")
    not_planned = deps_bot.DepStatus("closed", "not_planned")
    open_issue = deps_bot.DepStatus("open", None)

    assert deps_bot.deps_satisfied(frozenset(), {}) is True
    assert deps_bot.deps_satisfied(frozenset({3, 12}), {3: completed, 12: completed}) is True
    assert deps_bot.deps_satisfied(frozenset({3, 12}), {3: completed, 12: open_issue}) is False
    assert deps_bot.deps_satisfied(frozenset({3}), {3: None}) is False
    assert deps_bot.deps_satisfied(frozenset({3}), {3: not_planned}) is False


@pytest.mark.unit
def test_deps_satisfied_rejects_not_planned_with_waiting_label() -> None:
    completed = deps_bot.DepStatus("closed", "completed")
    not_planned = deps_bot.DepStatus("closed", "not_planned")
    states = {3: completed, 7: not_planned}

    assert deps_bot.deps_satisfied(frozenset({3, 7}), states) is False
    assert deps_bot.waiting_deps(frozenset({3, 7}), states) == ["#7 (closed:not_planned)"]


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


class _FakeOpener:
    def __init__(self, outcomes: list[Exception | bytes]) -> None:
        self.outcomes = iter(outcomes)
        self.calls = 0

    def __call__(self, _request: Any, *, timeout: int) -> BytesIO:
        assert timeout == 60
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return BytesIO(outcome)


def _http_error(status: int, *, body: bytes = b"error", retry_after: str | None = None) -> Any:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError(
        "https://api.github.com/repos/example/repo/issues",
        status,
        "error",
        headers,
        BytesIO(body),
    )


@pytest.mark.unit
def test_request_retries_connection_and_timeout_then_succeeds() -> None:
    opener = _FakeOpener(
        [http.client.RemoteDisconnected("closed"), TimeoutError("timed out"), b'{"ok": true}']
    )
    delays: list[float] = []
    client = deps_bot.GitHubClient(
        "token", "example/repo", opener=opener, sleep=delays.append, jitter=lambda: 0.25
    )

    assert client._request("GET", "/repos/example/repo/issues") == {"ok": True}
    assert opener.calls == 3
    assert delays == [1.25, 2.25]


@pytest.mark.unit
def test_request_gives_up_after_three_server_errors() -> None:
    opener = _FakeOpener([_http_error(503) for _ in range(3)])
    delays: list[float] = []
    client = deps_bot.GitHubClient(
        "token", "example/repo", opener=opener, sleep=delays.append, jitter=lambda: 0.0
    )

    with pytest.raises(RuntimeError, match="503"):
        client._request("GET", "/repos/example/repo/issues")
    assert opener.calls == 3
    assert delays == [1.0, 2.0]


@pytest.mark.unit
def test_request_allow_404_returns_without_retry() -> None:
    opener = _FakeOpener([_http_error(404)])
    delays: list[float] = []
    client = deps_bot.GitHubClient("token", "example/repo", opener=opener, sleep=delays.append)

    assert client._request("GET", "/repos/example/repo/issues/404", allow_404=True) is None
    assert opener.calls == 1
    assert delays == []


@pytest.mark.unit
@pytest.mark.parametrize("status", [400, 403, 404, 422])
def test_request_does_not_retry_other_client_errors(status: int) -> None:
    opener = _FakeOpener([_http_error(status)])
    delays: list[float] = []
    client = deps_bot.GitHubClient("token", "example/repo", opener=opener, sleep=delays.append)

    with pytest.raises(RuntimeError, match=str(status)):
        client._request("GET", "/repos/example/repo/issues")
    assert opener.calls == 1
    assert delays == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "expected_delay"),
    [
        (_http_error(429, retry_after="8"), 8.0),
        (_http_error(429), 60.5),
        (_http_error(403, body=b"You have exceeded a secondary rate limit."), 60.5),
        (_http_error(403, retry_after="10"), 10.0),
    ],
)
def test_request_retries_rate_limit_and_honours_retry_after(
    error: Exception, expected_delay: float
) -> None:
    opener = _FakeOpener([error, b"{}"])
    delays: list[float] = []
    client = deps_bot.GitHubClient(
        "token", "example/repo", opener=opener, sleep=delays.append, jitter=lambda: 0.5
    )

    assert client._request("GET", "/repos/example/repo/issues") == {}
    assert opener.calls == 2
    assert delays == [expected_delay]


@pytest.mark.unit
def test_request_retries_url_errors() -> None:
    opener = _FakeOpener([urllib.error.URLError("connection lost"), b"{}"])
    delays: list[float] = []
    client = deps_bot.GitHubClient(
        "token", "example/repo", opener=opener, sleep=delays.append, jitter=lambda: 0.0
    )

    assert client._request("GET", "/repos/example/repo/issues") == {}
    assert opener.calls == 2
    assert delays == [1.0]


@pytest.mark.unit
def test_request_honours_http_date_retry_after() -> None:
    opener = _FakeOpener([_http_error(429, retry_after="Wed, 14 Oct 2026 12:00:08 GMT"), b"{}"])
    delays: list[float] = []
    client = deps_bot.GitHubClient(
        "token",
        "example/repo",
        opener=opener,
        sleep=delays.append,
        jitter=lambda: 0.0,
        now=lambda: datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
    )

    assert client._request("GET", "/repos/example/repo/issues") == {}
    assert delays == [8.0]
