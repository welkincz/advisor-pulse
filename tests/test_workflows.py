"""The two operational workflows share serialization and preserve failure evidence."""

import json
import os
import subprocess
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def load(name: str) -> dict:
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def test_weekly_and_backfill_share_the_state_lock_and_failure_artifacts() -> None:
    for name in ("weekly.yml", "backfill.yml"):
        workflow = load(name)
        assert workflow["concurrency"] == {"group": "weekly", "cancel-in-progress": "false"}
        steps = workflow["jobs"]["run"]["steps"]
        assert any("uv run pulse" in step.get("run", "") for step in steps)
        assert any(
            step.get("name", "").startswith("Summarize") and step.get("if") == "always()"
            for step in steps
        )
        assert any(
            step.get("uses", "").startswith("actions/upload-artifact@")
            and step.get("if") == "always()"
            for step in steps
        )
        assert "ANTHROPIC_API_KEY" not in (WORKFLOWS / name).read_text()


def test_weekly_has_schedule_and_backfill_has_typed_dispatch_inputs() -> None:
    weekly = load("weekly.yml")
    backfill = load("backfill.yml")
    assert weekly["on"]["schedule"] == [{"cron": "0 11 * * 1"}]
    assert "workflow_dispatch" in weekly["on"]
    inputs = backfill["on"]["workflow_dispatch"]["inputs"]
    assert inputs["from"]["required"] == "true"
    assert inputs["to"]["required"] == "true"
    assert inputs["rebuild"]["type"] == "boolean"


def test_summary_steps_handle_success_and_missing_log(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "exports" / "run_log.json"
    source = json.loads(fixture.read_text())
    for name in ("weekly.yml", "backfill.yml"):
        step = next(
            step
            for step in load(name)["jobs"]["run"]["steps"]
            if step.get("name", "").startswith("Summarize")
        )
        for has_log in (True, False):
            data_dir = tmp_path / name / str(has_log)
            data_dir.mkdir(parents=True)
            if has_log:
                doc = json.loads(json.dumps(source))
                if name == "backfill.yml":
                    for run in doc["runs"][:2]:
                        run["run_type"] = "BACKFILL"
                (data_dir / "exports").mkdir()
                (data_dir / "exports" / "run_log.json").write_text(json.dumps(doc))
            summary = data_dir / "summary.md"
            subprocess.run(
                ["bash", "-eu", "-o", "pipefail", "-c", step["run"]],
                env={
                    "PATH": os.environ["PATH"],
                    "PULSE_DATA_DIR": str(data_dir),
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "FROM_WEEK": "2026-W39",
                    "TO_WEEK": "2026-W40",
                },
                check=True,
            )
            checks = json.loads((data_dir / "artifacts" / "check_results.json").read_text())
            expected = (1 if name == "weekly.yml" else 2) if has_log else 0
            assert len(checks["runs"]) == expected
            assert ("| Stage |" if has_log else "No run log") in summary.read_text()
