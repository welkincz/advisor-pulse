"""Alert lifecycle and workflow wiring, with no network calls."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pulse.contracts.enums import CheckStatus, StageStatus
from pulse.contracts.exports import RunLogExport
from pulse.runner import alert
from pulse.runner.alert import sync_alert

FIXTURE = Path(__file__).parents[2] / "fixtures" / "exports" / "run_log.json"
WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "weekly.yml"
RUN_URL = "https://github.com/welkincz/advisor-pulse/actions/runs/123"
SECRET = "secret-from-a-stage-message"


class FakeGitHub:
    def __init__(self) -> None:
        self.label_exists = False
        self.issue: dict[str, object] | None = None
        self.created = 0
        self.updated = 0
        self.comments: list[str] = []

    def ensure_label(self) -> None:
        self.label_exists = True

    def open_alert(self) -> int | None:
        return 7 if self.issue and self.issue["state"] == "open" else None

    def create_issue(self, title: str, body: str) -> int:
        assert self.label_exists
        self.issue = {"title": title, "body": body, "state": "open"}
        self.created += 1
        return 7

    def update_issue(self, number: int, body: str) -> None:
        assert number == 7 and self.issue is not None
        self.issue["body"] = body
        self.updated += 1

    def comment_issue(self, number: int, body: str) -> None:
        assert number == 7
        self.comments.append(body)

    def close_issue(self, number: int) -> None:
        assert number == 7 and self.issue is not None
        self.issue["state"] = "closed"


def _run_log(*, failed: bool = False, week: str = "2026-W40") -> RunLogExport:
    log = RunLogExport.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    run = log.runs[0]
    if failed:
        stages = [
            stage.model_copy(update={"status": StageStatus.FAILED, "message": SECRET})
            if stage.stage == "checks"
            else stage
            for stage in run.stages
        ]
        checks = [
            check.model_copy(update={"status": CheckStatus.FAIL, "message": SECRET})
            if check.check_id == "DQ030"
            else check
            for check in run.checks
        ]
        run = run.model_copy(
            update={"status": StageStatus.FAILED, "stages": stages, "checks": checks}
        )
    run = run.model_copy(update={"iso_week_id": week})
    return log.model_copy(update={"runs": [run]})


def test_first_failure_opens_one_labelled_issue_with_failed_stage_and_check() -> None:
    github = FakeGitHub()
    payloads: list[dict[str, str]] = []

    sync_alert(_run_log(failed=True), github, RUN_URL, webhook=payloads.append)

    assert github.created == 1
    assert github.updated == 0
    assert github.issue is not None
    body = str(github.issue["body"])
    assert "| checks | FAILED |" in body
    assert "| DQ030 | FAIL |" in body
    assert RUN_URL in body
    assert payloads and payloads[0]["status"] == "FAILED"


def test_second_failure_updates_the_same_open_issue() -> None:
    github = FakeGitHub()
    sync_alert(_run_log(failed=True), github, RUN_URL)

    sync_alert(_run_log(failed=True, week="2026-W41"), github, RUN_URL)

    assert github.created == 1
    assert github.updated == 1
    assert github.issue is not None
    assert "2026-W41" in str(github.issue["body"])
    assert github.issue["state"] == "open"


def test_terminal_stage_status_wins_over_running_row_for_the_same_attempt() -> None:
    github = FakeGitHub()
    log = _run_log(failed=True)
    run = log.runs[0]
    checks = next(stage for stage in run.stages if stage.stage == "checks")
    running = checks.model_copy(update={"status": StageStatus.RUNNING})
    stages = [running, *run.stages]

    with_attempts = log.model_copy(update={"runs": [run.model_copy(update={"stages": stages})]})
    sync_alert(with_attempts, github, RUN_URL)

    assert github.issue is not None
    assert "| Stage | checks | FAILED |" in str(github.issue["body"])


@pytest.mark.parametrize("status", [StageStatus.SUCCESS, StageStatus.WARN])
def test_healthy_run_after_failure_comments_and_closes_the_issue(status: StageStatus) -> None:
    github = FakeGitHub()
    payloads: list[dict[str, str]] = []
    sync_alert(_run_log(failed=True), github, RUN_URL)
    log = _run_log()
    run = log.runs[0].model_copy(update={"status": status})

    sync_alert(log.model_copy(update={"runs": [run]}), github, RUN_URL, webhook=payloads.append)

    assert github.issue is not None and github.issue["state"] == "closed"
    assert len(github.comments) == 1
    assert status.value in github.comments[0]
    assert RUN_URL in github.comments[0]
    assert payloads[0]["status"] == status.value


def test_success_without_open_alert_does_nothing() -> None:
    github = FakeGitHub()
    payloads: list[dict[str, str]] = []
    log = _run_log()
    run = log.runs[0].model_copy(update={"status": StageStatus.SUCCESS})

    sync_alert(log.model_copy(update={"runs": [run]}), github, RUN_URL, webhook=payloads.append)

    assert github.issue is None
    assert github.comments == []
    assert payloads == []


def test_failed_workflow_without_run_log_still_opens_an_actionable_issue() -> None:
    github = FakeGitHub()

    sync_alert(None, github, RUN_URL, workflow_failed=True)

    assert github.created == 1
    assert github.issue is not None
    assert "| Workflow | setup or post-run step | FAILED |" in str(github.issue["body"])
    assert RUN_URL in str(github.issue["body"])


def test_alert_body_and_webhook_omit_free_text_that_may_contain_secrets() -> None:
    github = FakeGitHub()
    payloads: list[dict[str, str]] = []
    log = _run_log(failed=True)
    run = log.runs[0]
    stages = [
        stage.model_copy(update={"stage": SECRET}) if stage.stage == "checks" else stage
        for stage in run.stages
    ]
    log = log.model_copy(update={"runs": [run.model_copy(update={"stages": stages})]})

    sync_alert(log, github, RUN_URL, webhook=payloads.append)

    assert github.issue is not None
    assert SECRET not in str(github.issue)
    assert SECRET not in str(payloads)
    assert "Restored warehouse" not in str(github.issue)
    assert "unknown stage" in str(github.issue)


def test_webhook_is_posted_only_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = FakeGitHub()
    sent: list[tuple[str, dict[str, str]]] = []
    path = tmp_path / "exports" / "run_log.json"
    path.parent.mkdir()
    path.write_text(_run_log(failed=True).model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(alert, "RestGitHubIssues", lambda repository, token: github)
    monkeypatch.setattr(alert, "_post_webhook", lambda url, payload: sent.append((url, payload)))
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_TOKEN", SECRET)
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "welkincz/advisor-pulse")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("PULSE_JOB_STATUS", "failure")
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    alert.main()
    assert sent == []

    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://example.test/webhook-secret")
    alert.main()
    assert len(sent) == 1
    assert sent[0][0] == "https://example.test/webhook-secret"
    assert SECRET not in str(sent[0][1])
    assert "webhook-secret" not in str(sent[0][1])


def test_weekly_workflow_wires_force_fail_and_always_alert() -> None:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    dispatch = workflow["on"]["workflow_dispatch"]["inputs"]
    assert dispatch["force_fail"]["type"] == "boolean"
    assert dispatch["force_fail"]["default"] == "false"
    assert workflow["permissions"]["issues"] == "write"
    steps = workflow["jobs"]["run"]["steps"]
    run_step = next(step for step in steps if step.get("name") == "Run last complete week")
    assert "PULSE_FORCE_FAIL" in run_step["env"]
    alert_step = next(step for step in steps if step.get("name") == "Sync pipeline alert issue")
    assert alert_step["if"] == "always()"
    assert "ALERT_WEBHOOK_URL" in alert_step["env"]
    assert "GITHUB_TOKEN" in alert_step["env"]
