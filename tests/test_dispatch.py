"""Unit tests for scripts/dispatch.py: the pure planning rules and the GitHub calls."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dispatch.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("dispatch", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dispatch = _load()
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
CURSOR = "agent:cursor"
READY = "status:ready"
WORKING = "status:in-progress"


def issue(number: int, *labels: str, comments: tuple[tuple[str, int], ...] = ()) -> Any:
    """``comments`` are (dispatcher kind, hours ago)."""
    return dispatch.Issue(
        number,
        frozenset(labels),
        tuple(
            dispatch.Comment(dispatch.MARKER.format(kind=kind), NOW - timedelta(hours=hours))
            for kind, hours in comments
        ),
    )


def kinds(actions: list[Any]) -> list[tuple[str, int]]:
    return [(a.kind, a.number) for a in actions]


def test_dispatches_lowest_numbers_up_to_the_cap() -> None:
    issues = [issue(n, CURSOR, READY) for n in (30, 22, 25)]
    assert kinds(dispatch.plan(issues, set(), NOW)) == [("dispatch", 22), ("dispatch", 25)]


def test_working_issues_use_slots_but_ones_in_review_do_not() -> None:
    issues = [
        issue(10, CURSOR, WORKING, comments=(("dispatch", 1),)),
        issue(11, CURSOR, WORKING, comments=(("dispatch", 1),)),  # its PR is open
        issue(20, CURSOR, READY),
        issue(21, CURSOR, READY),
    ]
    assert kinds(dispatch.plan(issues, {11}, NOW)) == [("dispatch", 20)]
    assert dispatch.plan(issues, set(), NOW) == []


def test_other_agents_and_claimed_issues_are_never_touched() -> None:
    issues = [
        issue(5, "agent:claude", READY),
        issue(6, CURSOR, WORKING),  # claimed by hand: no dispatcher marker
        issue(7, CURSOR, READY, WORKING),
    ]
    assert dispatch.plan(issues, set(), NOW) == []


def test_quiet_issue_is_nudged_twice_then_escalated_once() -> None:
    def step(*comments: tuple[str, int]) -> list[tuple[str, int]]:
        return kinds(dispatch.plan([issue(9, CURSOR, WORKING, comments=comments)], set(), NOW))

    assert step(("dispatch", 23)) == []
    assert step(("dispatch", 25)) == [("nudge", 9)]
    assert step(("dispatch", 60), ("nudge", 2)) == []  # the nudge reset the clock
    assert step(("dispatch", 60), ("nudge", 30)) == [("nudge", 9)]
    assert step(("dispatch", 90), ("nudge", 60), ("nudge", 30)) == [("escalate", 9)]
    assert step(("dispatch", 120), ("nudge", 90), ("nudge", 60), ("escalate", 30)) == []
    with_pr = [issue(9, CURSOR, WORKING, comments=(("dispatch", 99),))]
    assert dispatch.plan(with_pr, {9}, NOW) == []


def test_open_prs_are_matched_by_body_or_branch() -> None:
    prs = [
        {"body": "## Summary\n...\nCloses #22", "head": {"ref": "dbt/22-staging"}},
        {"body": "fixes #31 and resolves #32", "head": {"ref": "geo/31-fsa"}},
        {"body": None, "head": {"ref": "ingest/18-teradata-client"}},
        {"body": "Related: #40", "head": {"ref": "cursor/some-branch"}},
    ]
    assert dispatch.issues_with_open_prs(prs) == {18, 22, 31, 32}


def test_comment_bodies_carry_marker_mention_and_rules() -> None:
    body = dispatch.comment_body(dispatch.Action("dispatch", 22, CURSOR))
    assert body.startswith("<!-- dispatcher:dispatch -->\n@cursor ")
    assert "Closes #22" in body and "Do not merge" in body
    assert "@cursor" in dispatch.comment_body(dispatch.Action("nudge", 22, CURSOR))
    escalate = dispatch.comment_body(dispatch.Action("escalate", 22, CURSOR))
    assert dispatch.OWNER in escalate and "@cursor" not in escalate


class FakeClient:
    def __init__(self, issues: list[dict[str, Any]], prs: list[dict[str, Any]]) -> None:
        self.issues = issues
        self.prs = prs
        self.calls: list[tuple[str, int, Any]] = []
        self.comments: dict[int, list[dict[str, Any]]] = {}

    def list_agent_issues(self, agent_label: str) -> list[dict[str, Any]]:
        return [i for i in self.issues if agent_label in {lb["name"] for lb in i["labels"]}]

    def list_open_prs(self) -> list[dict[str, Any]]:
        return self.prs

    def list_comments(self, number: int) -> list[dict[str, Any]]:
        return self.comments.get(number, [])

    def create_comment(self, number: int, body: str) -> None:
        self.calls.append(("comment", number, body.splitlines()[0]))

    def remove_label(self, number: int, label: str) -> None:
        self.calls.append(("remove", number, label))

    def add_labels(self, number: int, labels: list[str]) -> None:
        self.calls.append(("add", number, labels))


def _raw(number: int, *labels: str) -> dict[str, Any]:
    return {"number": number, "labels": [{"name": name} for name in labels]}


def test_run_comments_then_moves_the_label(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeClient(
        [_raw(22, CURSOR, READY), _raw(23, CURSOR, "status:blocked")],
        [],
    )
    assert dispatch.run(client, NOW) == 0
    assert client.calls == [
        ("comment", 22, "<!-- dispatcher:dispatch -->"),
        ("remove", 22, READY),
        ("add", 22, [WORKING]),
    ]
    assert "#22: dispatch" in capsys.readouterr().out


def test_run_reads_comment_times_for_in_progress_issues() -> None:
    client = FakeClient([_raw(9, CURSOR, WORKING)], [])
    client.comments[9] = [
        {"body": "<!-- dispatcher:dispatch -->\n@cursor ...", "created_at": "2026-10-15T08:00:00Z"},
        {"body": "Taking a look!", "created_at": "2026-10-15T08:01:00Z"},
    ]
    dispatch.run(client, NOW)
    assert client.calls == [("comment", 9, "<!-- dispatcher:nudge -->")]


def test_main_requires_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DISPATCH_TOKEN", "GITHUB_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(name, raising=False)
    assert dispatch.main([]) == 2
