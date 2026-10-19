"""Open, update, and resolve the one GitHub issue for a failed weekly run."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from pulse.contracts.enums import CheckStatus, RunType, StageStatus
from pulse.contracts.exports import RunLogExport, RunSummary, StageAttempt
from pulse.runner.dag import WEEKLY_STAGES

LABEL = "alert:pipeline"
TITLE = "[Pipeline alert] Weekly report failed"
Webhook = Callable[[dict[str, str]], None]
STAGE_NAMES = frozenset(stage.name for stage in WEEKLY_STAGES)


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
        with urlopen(request, timeout=15) as response:
            contents = response.read()
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
            if stage.status is StageStatus.FAILED:
                safe_name = name if name in STAGE_NAMES else "unknown stage"
                rows.append(f"| Stage | {safe_name} | FAILED |")
        for check in run.checks:
            if check.status is CheckStatus.FAIL:
                rows.append(f"| Check | {check.check_id} | FAIL |")
    if len(rows) == 2 and workflow_failed:
        rows.append("| Workflow | setup or post-run step | FAILED |")
    return rows


def _body(run: RunSummary | None, run_url: str, *, workflow_failed: bool) -> str:
    week = run.iso_week_id if run is not None else "unknown"
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
    run = next((r for r in log.runs if r.run_type is RunType.WEEKLY), None) if log else None
    if run is None and not workflow_failed:
        return
    failed = workflow_failed or (run is not None and run.status is StageStatus.FAILED)
    if failed:
        github.ensure_label()
        body = _body(run, run_url, workflow_failed=workflow_failed)
        number = github.open_alert()
        if number is None:
            github.create_issue(TITLE, body)
        else:
            github.update_issue(number, body)
        status = "FAILED"
    elif run is not None and run.status in {StageStatus.SUCCESS, StageStatus.WARN}:
        number = github.open_alert()
        if number is None:
            return
        status = run.status.value
        github.comment_issue(
            number,
            f"Weekly report {run.iso_week_id} finished {status}. "
            f"[GitHub Actions run]({run_url}). Closing this alert.",
        )
        github.close_issue(number)
    else:
        return
    if webhook is not None:
        week = run.iso_week_id if run is not None else "unknown"
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
        RunLogExport.model_validate_json(path.read_text(encoding="utf-8"))
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
            except URLError:
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
