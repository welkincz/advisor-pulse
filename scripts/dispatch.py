#!/usr/bin/env python3
"""Hand ready issues to cloud coding agents, and nudge the ones that went quiet (issue #99).

Triggered by .github/workflows/dispatch.yml. For each agent in AGENTS:

- **dispatch**: `status:ready` issues with the agent's label get a comment that mentions the
  agent, lowest number first, while fewer than CAP of its dispatched issues are still
  working (an issue with an open PR is waiting for review and does not count).
- **nudge**: a dispatched `status:in-progress` issue with no open PR and no dispatcher
  comment for STALE_HOURS gets the mention again, at most MAX_NUDGES times.
- **escalate**: after that, the owner is asked to look, once.

Issues without a dispatcher comment were claimed by someone else and are never touched.
The decisions are pure functions (``plan``); the GitHub calls reuse deps_bot.GitHubClient.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.parse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deps_bot import LABEL_IN_PROGRESS, LABEL_READY, GitHubClient, label_names

# Agent label → the mention that starts that agent's cloud run.
AGENTS: Mapping[str, str] = {"agent:cursor": "@cursor"}
CAP = 2
STALE_HOURS = 24
MAX_NUDGES = 2
OWNER = "@welkincz"

MARKER = "<!-- dispatcher:{kind} -->"
CLOSES_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b", re.IGNORECASE)
BRANCH_RE = re.compile(r"^[a-z]+/(\d+)-")


@dataclass(frozen=True)
class Comment:
    body: str
    created_at: datetime


@dataclass(frozen=True)
class Issue:
    number: int
    labels: frozenset[str]
    comments: tuple[Comment, ...] = ()

    def markers(self, kind: str) -> list[Comment]:
        tag = MARKER.format(kind=kind)
        return [c for c in self.comments if tag in c.body]

    @property
    def dispatched(self) -> bool:
        return bool(self.markers("dispatch"))

    def last_activity(self) -> datetime | None:
        """Time of the newest dispatcher comment of any kind."""
        ours = [c.created_at for c in self.comments if "<!-- dispatcher:" in c.body]
        return max(ours, default=None)


@dataclass(frozen=True)
class Action:
    kind: str  # dispatch | nudge | escalate
    number: int
    agent: str


def issues_with_open_prs(prs: Iterable[Mapping[str, Any]]) -> set[int]:
    """Issue numbers an open PR closes, from its body or its `<area>/<N>-slug` branch."""
    numbers: set[int] = set()
    for pr in prs:
        numbers.update(int(n) for n in CLOSES_RE.findall(pr.get("body") or ""))
        branch = BRANCH_RE.match((pr.get("head") or {}).get("ref") or "")
        if branch:
            numbers.add(int(branch.group(1)))
    return numbers


def plan(
    issues: Iterable[Issue],
    open_pr_issues: set[int],
    now: datetime,
    *,
    cap: int = CAP,
    stale: timedelta = timedelta(hours=STALE_HOURS),
    max_nudges: int = MAX_NUDGES,
) -> list[Action]:
    actions: list[Action] = []
    issues = sorted(issues, key=lambda i: i.number)
    for agent in AGENTS:
        mine = [i for i in issues if agent in i.labels]
        working = [
            i
            for i in mine
            if LABEL_IN_PROGRESS in i.labels and i.dispatched and i.number not in open_pr_issues
        ]
        for issue in working:
            last = issue.last_activity()
            if last is None or now - last < stale or issue.markers("escalate"):
                continue
            kind = "nudge" if len(issue.markers("nudge")) < max_nudges else "escalate"
            actions.append(Action(kind, issue.number, agent))
        slots = max(0, cap - len(working))
        ready = [i for i in mine if LABEL_READY in i.labels and LABEL_IN_PROGRESS not in i.labels]
        actions.extend(Action("dispatch", i.number, agent) for i in ready[:slots])
    return actions


def comment_body(action: Action) -> str:
    mention = AGENTS[action.agent]
    marker = MARKER.format(kind=action.kind)
    if action.kind == "escalate":
        return (
            f"{marker}\n{OWNER} this issue has been in progress for "
            f"{STALE_HOURS * (MAX_NUDGES + 1)} h with no PR after {MAX_NUDGES} nudges. "
            "Please check the agent run, or set `status:ready` to dispatch it again."
        )
    if action.kind == "nudge":
        return (
            f"{marker}\n{mention} there is no PR for this issue yet. Please continue: finish "
            "the acceptance criteria and open the PR (`Closes "
            f"#{action.number}`), or comment here with what is blocking you."
        )
    return (
        f"{marker}\n{mention} please implement this issue.\n\n"
        "- Read `AGENTS.md`, `docs/PLAN.md` and the contracts this issue depends on first.\n"
        f"- Branch `<area>/{action.number}-<slug>` from `main`; stay inside the issue's "
        '"Owns" paths.\n'
        "- Run the issue's Verify commands and `make check`; paste the output in the PR body.\n"
        f"- Open a PR with `Closes #{action.number}`, then **stop. Do not merge.** "
        "Claude reviews and merges."
    )


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class DispatchClient(GitHubClient):
    def list_agent_issues(self, agent_label: str) -> list[dict[str, Any]]:
        label = urllib.parse.quote(agent_label)
        items = self._paginate(f"/repos/{self.repo}/issues?state=open&labels={label}")
        return [i for i in items if "pull_request" not in i]

    def list_open_prs(self) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{self.repo}/pulls?state=open")


def load_issues(client: DispatchClient) -> list[Issue]:
    issues: dict[int, Issue] = {}
    for agent in AGENTS:
        for raw in client.list_agent_issues(agent):
            labels = frozenset(label_names(raw))
            if not labels & {LABEL_READY, LABEL_IN_PROGRESS}:
                continue
            number = int(raw["number"])
            comments: tuple[Comment, ...] = ()
            if LABEL_IN_PROGRESS in labels:
                comments = tuple(
                    Comment(c.get("body") or "", _parse_time(c["created_at"]))
                    for c in client.list_comments(number)
                )
            issues[number] = Issue(number, labels, comments)
    return list(issues.values())


def apply(client: DispatchClient, action: Action) -> None:
    client.create_comment(action.number, comment_body(action))
    if action.kind == "dispatch":
        client.remove_label(action.number, LABEL_READY)
        client.add_labels(action.number, [LABEL_IN_PROGRESS])
    print(f"#{action.number}: {action.kind} ({action.agent})")


def run(client: DispatchClient, now: datetime) -> int:
    issues = load_issues(client)
    open_prs = issues_with_open_prs(client.list_open_prs())
    actions = plan(issues, open_prs, now)
    print(f"{len(issues)} agent issue(s), {len(open_prs)} with open PRs, {len(actions)} action(s)")
    for action in actions:
        apply(client, action)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="Print actions, change nothing.")
    args = parser.parse_args(argv)
    token = os.environ.get("DISPATCH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print(
            "DISPATCH_TOKEN or GITHUB_TOKEN, and GITHUB_REPOSITORY, are required", file=sys.stderr
        )
        return 2
    if not os.environ.get("DISPATCH_TOKEN"):
        print("warning: DISPATCH_TOKEN is not set; agents may ignore mentions from a bot")
    return run(DispatchClient(token, repo, dry_run=args.dry_run), datetime.now(UTC))


if __name__ == "__main__":
    raise SystemExit(main())
