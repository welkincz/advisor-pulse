#!/usr/bin/env python3
"""Flip status:blocked → status:ready when every Depends on issue is closed.

Triggered by .github/workflows/deps.yml on issue closed / edited.
Uses GITHUB_TOKEN only (no extra secrets).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

DEPENDS_ON_RE = re.compile(r"^Depends on:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)
ISSUE_REF_RE = re.compile(r"#(\d+)")

READY_COMMENT_MARKER = "<!-- deps-bot:ready -->"
READY_COMMENT_BODY = (
    f"{READY_COMMENT_MARKER}\n"
    "All dependencies are closed. Relabelled `status:blocked` → `status:ready`."
)

LABEL_BLOCKED = "status:blocked"
LABEL_READY = "status:ready"
LABEL_IN_PROGRESS = "status:in-progress"

API_ROOT = "https://api.github.com"


def parse_depends_on(body: str | None) -> frozenset[int] | None:
    """Parse the Depends on line from an issue body.

    Returns:
      - frozenset of issue numbers for `#3` / `#3, #12` (whitespace-tolerant)
      - empty frozenset for `none` (case-insensitive)
      - None if the body has no Depends on line
    """
    if body is None:
        return None
    match = DEPENDS_ON_RE.search(body)
    if match is None:
        return None
    value = match.group(1).strip()
    if not value or value.lower() == "none":
        return frozenset()
    return frozenset(int(num) for num in ISSUE_REF_RE.findall(value))


def label_names(issue: dict[str, Any]) -> set[str]:
    return {label["name"] for label in issue.get("labels", [])}


def should_process(issue: dict[str, Any]) -> bool:
    """Open blocked issues only; never touch status:in-progress."""
    if issue.get("state") != "open":
        return False
    if "pull_request" in issue:
        return False
    labels = label_names(issue)
    if LABEL_IN_PROGRESS in labels:
        return False
    return LABEL_BLOCKED in labels


def has_ready_comment(comments: Iterable[dict[str, Any]]) -> bool:
    return any(READY_COMMENT_MARKER in (comment.get("body") or "") for comment in comments)


@dataclass(frozen=True)
class DepStatus:
    """GitHub issue state used to decide whether a dependency counts as done."""

    state: str
    state_reason: str | None

    @property
    def satisfied(self) -> bool:
        """Only completed closures count; not_planned / duplicate do not."""
        return self.state == "closed" and self.state_reason == "completed"

    def waiting_label(self) -> str:
        if self.state != "closed":
            return self.state
        reason = self.state_reason or "unspecified"
        return f"closed:{reason}"


class GitHubClient:
    """Minimal GitHub REST client (stdlib urllib, GITHUB_TOKEN)."""

    def __init__(self, token: str, repo: str, *, dry_run: bool = False) -> None:
        if "/" not in repo:
            raise ValueError(f"GITHUB_REPOSITORY must be owner/name, got {repo!r}")
        self.token = token
        self.repo = repo
        self.dry_run = dry_run

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> Any:
        url = f"{API_ROOT}{path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "advisor-pulse-deps-bot",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc

    def _paginate(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            sep = "&" if "?" in path else "?"
            chunk = self._request("GET", f"{path}{sep}per_page=100&page={page}")
            if not chunk:
                break
            if not isinstance(chunk, list):
                raise TypeError(f"expected list from {path}, got {type(chunk).__name__}")
            items.extend(chunk)
            if len(chunk) < 100:
                break
            page += 1
        return items

    def list_blocked_issues(self) -> list[dict[str, Any]]:
        label = urllib.parse.quote(LABEL_BLOCKED)
        return self._paginate(f"/repos/{self.repo}/issues?state=open&labels={label}")

    def get_issue(self, number: int) -> dict[str, Any] | None:
        result = self._request("GET", f"/repos/{self.repo}/issues/{number}", allow_404=True)
        return result if isinstance(result, dict) else None

    def dep_status(self, number: int) -> DepStatus | None:
        issue = self.get_issue(number)
        if issue is None:
            return None
        reason = issue.get("state_reason")
        return DepStatus(state=str(issue["state"]), state_reason=str(reason) if reason else None)

    def remove_label(self, number: int, label: str) -> None:
        encoded = urllib.parse.quote(label)
        path = f"/repos/{self.repo}/issues/{number}/labels/{encoded}"
        if self.dry_run:
            print(f"dry-run: DELETE {path}")
            return
        self._request("DELETE", path, allow_404=True)

    def add_labels(self, number: int, labels: list[str]) -> None:
        path = f"/repos/{self.repo}/issues/{number}/labels"
        if self.dry_run:
            print(f"dry-run: POST {path} {labels}")
            return
        self._request("POST", path, body={"labels": labels})

    def list_comments(self, number: int) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{self.repo}/issues/{number}/comments")

    def create_comment(self, number: int, body: str) -> None:
        path = f"/repos/{self.repo}/issues/{number}/comments"
        if self.dry_run:
            print(f"dry-run: POST {path}")
            return
        self._request("POST", path, body={"body": body})


def deps_satisfied(deps: frozenset[int], states: dict[int, DepStatus | None]) -> bool:
    """True when every dependency is closed as completed (empty deps ⇒ satisfied)."""

    def _ok(num: int) -> bool:
        status = states.get(num)
        return status is not None and status.satisfied

    return all(_ok(num) for num in deps)


def waiting_deps(deps: frozenset[int], states: dict[int, DepStatus | None]) -> list[str]:
    """Human-readable labels for dependencies that are not completed."""
    labels: list[str] = []
    for num in sorted(deps):
        status = states.get(num)
        if status is None:
            labels.append(f"#{num} (missing)")
        elif not status.satisfied:
            labels.append(f"#{num} ({status.waiting_label()})")
    return labels


def unblock_issue(client: GitHubClient, issue: dict[str, Any]) -> bool:
    """Swap labels and comment once. Returns True if a change was made."""
    number = int(issue["number"])
    comments = client.list_comments(number)
    already_commented = has_ready_comment(comments)

    labels = label_names(issue)
    needs_label_swap = LABEL_BLOCKED in labels and LABEL_READY not in labels

    if not needs_label_swap and already_commented:
        return False

    if needs_label_swap:
        client.remove_label(number, LABEL_BLOCKED)
        if LABEL_READY not in labels:
            client.add_labels(number, [LABEL_READY])
        print(f"#{number}: {LABEL_BLOCKED} → {LABEL_READY}")

    if not already_commented:
        client.create_comment(number, READY_COMMENT_BODY)
        print(f"#{number}: posted ready comment")

    return True


def run(client: GitHubClient) -> int:
    blocked = client.list_blocked_issues()
    candidates = [issue for issue in blocked if should_process(issue)]
    print(f"scanned {len(blocked)} blocked issue(s); {len(candidates)} candidate(s)")

    changed = 0
    state_cache: dict[int, DepStatus | None] = {}

    for issue in candidates:
        number = int(issue["number"])
        deps = parse_depends_on(issue.get("body"))
        if deps is None:
            print(f"#{number}: no Depends on line; skip")
            continue

        missing = [dep for dep in deps if dep not in state_cache]
        for dep in missing:
            state_cache[dep] = client.dep_status(dep)

        if not deps_satisfied(deps, state_cache):
            waiting = waiting_deps(deps, state_cache)
            print(f"#{number}: still waiting on {', '.join(waiting)}")
            continue

        if unblock_issue(client, issue):
            changed += 1

    print(f"done; unblocked {changed} issue(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print mutations without calling write endpoints",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("GITHUB_TOKEN and GITHUB_REPOSITORY are required", file=sys.stderr)
        return 2

    client = GitHubClient(token, repo, dry_run=args.dry_run)
    return run(client)


if __name__ == "__main__":
    raise SystemExit(main())
