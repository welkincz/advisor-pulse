"""Open, update, and resolve the one GitHub issue for a failed weekly run."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from random import random
from time import sleep
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from pulse.contracts.exports import RunLogExport, RunSummary, StageAttempt

LABEL = "alert:pipeline"
TITLE = "[Pipeline alert] Weekly report failed"
Webhook = Callable[[dict[str, str]], None]
# This allowlist keeps arbitrary run-log text out of a public issue. Keep it in
# sync with the weekly DAG; the test below verifies the names against that DAG.
STAGE_NAMES = frozenset(
    {
        "restore_state",
        "generate",
        "ingest",
        "dbt_build",
        "checks",
        "narrate",
        "export",
        "persist_state",
        "release_lock",
    }
)


class GitHubIssues(Protocol):
    def ensure_label(self) -> None: ...
    def open_alert(self) -> int | None: ...
    def create_issue(self, title: str, body: str) -> int: ...
    def update_issue(self, number: int, body: str) -> None: ...
    def comment_issue(self, number: int, body: str) -> None: ...
    def close_issue(self, number: int) -> None: ...


class RestGitHubIssues:
    """Small GitHub REST client; the lifecycle accepts a fake instead in tests."""

    def __init__(self, repository: str, token: str) -> None:
        self.base = f"https://api.github.com/repos/{repository}"
        self.token = token

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=15) as response:
                    contents = response.read()
                break
            except HTTPError as exc:
                if attempt == 2 or exc.code not in {429, 500, 502, 503, 504}:
                    raise
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise
            sleep(2**attempt + random())
        return json.loads(contents) if contents else None

    def ensure_label(self) -> None:
        try:
            self._request("GET", f"/labels/{quote(LABEL, safe='')}")
        except HTTPError as exc:
            if exc.code != 404:
                raise
            self._request(
                "POST",
                "/labels",
                {"name": LABEL, "color": "B60205", "description": "Weekly pipeline failure"},
            )

    def open_alert(self) -> int | None:
        query = urlencode({"state": "open", "labels": LABEL, "per_page": 100})
        issues = self._request("GET", f"/issues?{query}")
        return next((issue["number"] for issue in issues if "pull_request" not in issue), None)

    def create_issue(self, title: str, body: str) -> int:
        issue = self._request("POST", "/issues", {"title": title, "body": body, "labels": [LABEL]})
        return int(issue["number"])

    def update_issue(self, number: int, body: str) -> None:
        self._request("PATCH", f"/issues/{number}", {"body": body})

    def comment_issue(self, number: int, body: str) -> None:
        self._request("POST", f"/issues/{number}/comments", {"body": body})

    def close_issue(self, number: int) -> None:
        self._request("PATCH", f"/issues/{number}", {"state": "closed"})


def _failed_rows(run: RunSummary | None, *, workflow_failed: bool) -> list[str]:
    rows = ["| Kind | Name | Status |", "| --- | --- | --- |"]
    if run is not None:
        latest: dict[str, StageAttempt] = {}
        for stage in run.stages:
            if stage.stage not in latest or stage.attempt >= latest[stage.stage].attempt:
                latest[stage.stage] = stage
        for name, stage in latest.items():
            if stage.status == "FAILED":
                safe_name = name if name in STAGE_NAMES else "unknown stage"
                rows.append(f"| Stage | {safe_name} | FAILED |")
        for check in run.checks:
            if check.status == "FAIL":
                check_id = (
                    check.check_id if re.fullmatch(r"DQ\d{3}", check.check_id) else "unknown check"
                )
                rows.append(f"| Check | {check_id} | FAIL |")
    if len(rows) == 2 and workflow_failed:
        rows.append("| Workflow | setup or post-run step | FAILED |")
    return rows


def _body(run: RunSummary | None, run_url: str, *, workflow_failed: bool) -> str:
    week = _week(run)
    return "\n".join(
        [
            "## Weekly pipeline failure",
            "",
            f"Week: {week}",
            f"[GitHub Actions run]({run_url})",
            "",
            *_failed_rows(run, workflow_failed=workflow_failed),
            "",
        ]
    )


def sync_alert(
    log: RunLogExport | None,
    github: GitHubIssues,
    run_url: str,
    *,
    webhook: Webhook | None = None,
    workflow_failed: bool = False,
) -> None:
    """Reflect the latest weekly run in one alert issue. No free-text log fields leave here."""
    run = next((r for r in log.runs if r.run_type == "WEEKLY"), None) if log else None
    if run is None and not workflow_failed:
        return
    failed = workflow_failed or (run is not None and run.status == "FAILED")
    if failed:
        github.ensure_label()
        body = _body(run, run_url, workflow_failed=workflow_failed)
        number = github.open_alert()
        if number is None:
            github.create_issue(TITLE, body)
        else:
            github.update_issue(number, body)
        status = "FAILED"
    elif run is not None and run.status in {"SUCCESS", "WARN"}:
        number = github.open_alert()
        if number is None:
            return
        status = str(run.status)
        github.comment_issue(
            number,
            f"Weekly report {_week(run)} finished {status}. "
            f"[GitHub Actions run]({run_url}). Closing this alert.",
        )
        github.close_issue(number)
    else:
        return
    if webhook is not None:
        week = _week(run)
        summary = f"Advisor Pulse weekly report {status} for {week}."
        webhook({"status": status, "week": week, "text": summary, "content": summary})


def _run_url() -> str:
    server = os.environ["GITHUB_SERVER_URL"].rstrip("/")
    repository = os.environ["GITHUB_REPOSITORY"]
    run_id = os.environ["GITHUB_RUN_ID"]
    parsed = urlparse(server)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("GITHUB_SERVER_URL must be an HTTPS origin")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not run_id.isdecimal():
        raise ValueError("Invalid GitHub repository or run id")
    return f"{server}/{repository}/actions/runs/{run_id}"


def _week(run: RunSummary | None) -> str:
    if run is None:
        return "unknown"
    return run.iso_week_id if re.fullmatch(r"\d{4}-W\d{2}", run.iso_week_id) else "unknown"


def _post_webhook(url: str, payload: dict[str, str]) -> None:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15):
        pass


def main() -> None:
    path = Path(os.environ.get("PULSE_DATA_DIR", "data")) / "exports" / "run_log.json"
    log = (
        json.loads(
            path.read_text(encoding="utf-8"), object_hook=lambda item: SimpleNamespace(**item)
        )
        if path.exists()
        else None
    )
    token = os.environ["GITHUB_TOKEN"]
    github = RestGitHubIssues(os.environ["GITHUB_REPOSITORY"], token)
    webhook_url = os.environ.get("ALERT_WEBHOOK_URL")

    def notify(payload: dict[str, str]) -> None:
        if webhook_url:
            try:
                _post_webhook(webhook_url, payload)
            except Exception:
                print("Optional alert webhook failed.", file=sys.stderr)

    sync_alert(
        log,
        github,
        _run_url(),
        webhook=notify if webhook_url else None,
        workflow_failed=os.environ.get("PULSE_JOB_STATUS") == "failure",
    )


if __name__ == "__main__":
    main()
