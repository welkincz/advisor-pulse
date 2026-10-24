"""The two operational workflows share serialization and preserve failure evidence."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
PAGES_ACTION = Path(__file__).resolve().parents[1] / ".github" / "actions" / "pages-deploy"


def load(name: str) -> dict:
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def action_steps() -> list[dict[str, Any]]:
    action = yaml.load((PAGES_ACTION / "action.yml").read_text(), Loader=yaml.BaseLoader)
    assert action["runs"]["using"] == "composite"
    steps: list[dict[str, Any]] = action["runs"]["steps"]
    return steps


def action_step(step_id: str) -> dict[str, Any]:
    return next(step for step in action_steps() if step.get("id") == step_id)


def test_weekly_and_backfill_share_the_state_lock_and_failure_artifacts() -> None:
    for name in ("weekly.yml", "backfill.yml"):
        workflow = load(name)
        expected_group = (
            "weekly"
            if name == "weekly.yml"
            else (
                "${{ inputs.benchmark_only && format('backfill-benchmark-{0}', github.ref) || 'weekly' }}"
            )
        )
        assert workflow["concurrency"] == {"group": expected_group, "cancel-in-progress": "false"}
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
    assert inputs["budget_minutes"]["default"] == "320"


def test_backfill_that_stops_on_its_budget_continues_without_deploying() -> None:
    steps = {step.get("name"): step for step in load("backfill.yml")["jobs"]["run"]["steps"]}
    run = steps["Backfill selected weeks"]["run"]
    assert '--budget-minutes "$BUDGET_MINUTES"' in run
    assert 'echo "next=' in run
    assert steps["Build backfilled site"]["if"] == (
        "inputs.benchmark_only != true && steps.backfill_run.outputs.next == ''"
    )
    cont = steps["Continue in a new run"]
    assert cont["if"] == (
        "inputs.benchmark_only != true && "
        "steps.backfill_run.outcome == 'success' && steps.backfill_run.outputs.next != ''"
    )
    assert "gh workflow run backfill.yml" in cont["run"]
    assert "-f rebuild=false" in cont["run"]


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


@pytest.mark.parametrize(
    "name,run_id", [("weekly.yml", "weekly_run"), ("backfill.yml", "backfill_run")]
)
def test_workflows_call_the_shared_pages_action(name: str, run_id: str) -> None:
    workflow = load(name)
    chained = name == "backfill.yml"  # dispatches its own continuation (#206)
    assert workflow["permissions"]["actions"] == ("write" if chained else "read")
    steps = workflow["jobs"]["run"]["steps"]
    deploy = next(step for step in steps if step.get("uses") == "./.github/actions/pages-deploy")
    assert deploy["if"] == (
        "always() && inputs.benchmark_only != true && steps.backfill_run.outputs.next == ''"
        if chained
        else "always()"
    )
    assert deploy["with"]["run-outcome"] == f"${{{{ steps.{run_id}.outcome }}}}"
    assert deploy["with"]["build-outcome"] == "${{ steps.build_site.outcome }}"
    assert deploy["with"]["cloudflare-api-token"] == "${{ secrets.CLOUDFLARE_API_TOKEN }}"
    assert deploy["with"]["cloudflare-account-id"] == "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"
    assert "wrangler" not in (WORKFLOWS / name).read_text()
    names = [step.get("name") for step in steps]
    assert names.index("Deploy to Cloudflare Pages") < next(
        i for i, n in enumerate(names) if n and n.startswith("Summarize")
    )


def test_pages_action_is_guarded_and_can_restore_prior_artifact() -> None:
    by_name = {step.get("name"): step for step in action_steps()}
    for step in action_steps():
        if "run" in step:
            assert step["shell"] == "bash"
    guard = by_name["Check Cloudflare deployment credentials"]
    assert guard["if"] == "always()"
    assert guard["env"]["GIT_REF"] == "${{ github.ref }}"
    success = by_name["Deploy successful site"]
    assert "steps.cloudflare.outputs.available == 'true'" in success["if"]
    assert "inputs.run-outcome == 'success'" in success["if"]
    assert "inputs.build-outcome == 'success'" in success["if"]
    deploy_command = "npx --yes wrangler@4.151.1 pages deploy web/dist --project-name advisor-pulse"
    assert deploy_command in success["run"]
    assert success["env"]["CLOUDFLARE_API_TOKEN"] == "${{ inputs.cloudflare-api-token }}"
    archive = by_name["Save successful Pages artifact"]
    assert archive["if"] == "steps.deploy_pages.outcome == 'success'"
    assert archive["with"]["name"] == "pages-deploy-${{ github.run_id }}"
    recovery = by_name["Restore prior Pages deployment on failed run"]
    assert recovery["if"].startswith("always() && ")
    assert "inputs.run-outcome == 'failure'" in recovery["if"]
    assert "steps.cloudflare.outputs.available == 'true'" in recovery["if"]
    assert "gh run download" in recovery["run"]
    assert "data/exports/run_log.json" in recovery["run"]
    redeploy = by_name["Redeploy prior site with failed run log"]
    assert "steps.recovery.outputs.ready == 'true'" in redeploy["if"]
    assert deploy_command in redeploy["run"]


def test_pages_cache_headers_and_spa_fallback() -> None:
    public = Path(__file__).resolve().parents[1] / "web" / "public"
    headers = (public / "_headers").read_text()
    redirects = (public / "_redirects").read_text()
    assert "/data/manifest.json\n  Cache-Control: no-cache" in headers
    assert "/data/run_log.json\n  Cache-Control: no-cache" in headers
    assert "/assets/*\n  Cache-Control: public, max-age=31536000, immutable" in headers
    assert "/recap/*\n  Cache-Control: no-cache" in headers
    assert "/* /index.html 200" in redirects


@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/heads/feature"])
@pytest.mark.parametrize("token,account", [("", "account"), ("token", ""), ("token", "account")])
def test_cloudflare_guard_needs_main_and_both_secrets(
    ref: str, token: str, account: str, tmp_path: Path
) -> None:
    guard = action_step("cloudflare")
    summary = tmp_path / "summary.md"
    output = tmp_path / "output.txt"
    result = subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", guard["run"]],
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
            "CLOUDFLARE_API_TOKEN": token,
            "CLOUDFLARE_ACCOUNT_ID": account,
            "GIT_REF": ref,
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == result.stderr == ""
    deployable = token and account and ref == "refs/heads/main"
    assert output.read_text() == ("available=true\n" if deployable else "available=false\n")
    if not deployable:
        summary_text = summary.read_text()
        assert "deploy skipped" in summary_text
        if ref != "refs/heads/main":
            assert "only runs from main deploy" in summary_text
        for value in (token, account):
            if value:
                assert value not in summary_text


@pytest.mark.parametrize("artifact_present", [True, False])
@pytest.mark.parametrize("run_status", ["FAILED", "SUCCESS"])
def test_recovery_reuses_only_previous_site_and_new_run_log(
    artifact_present: bool, run_status: str, tmp_path: Path
) -> None:
    recovery = action_step("recovery")
    previous = tmp_path / "previous"
    (previous / "data").mkdir(parents=True)
    (previous / "index.html").write_text("old site")
    (previous / "data" / "manifest.json").write_text("old manifest")
    (previous / "data" / "weekly.parquet").write_text("old data")
    (previous / "data" / "run_log.json").write_text("old run log")
    (tmp_path / "web" / "dist").mkdir(parents=True)
    (tmp_path / "web" / "dist" / "bad-new-file").write_text("never deploy")
    (tmp_path / "data" / "exports").mkdir(parents=True)
    new_log = json.dumps({"runs": [{"status": run_status}]})
    (tmp_path / "data" / "exports" / "run_log.json").write_text(new_log)
    (tmp_path / "runner-temp").mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ $1 == api ]]; then\n"
        "  if [[ $ARTIFACT_PRESENT == true ]]; then\n"
        "    printf '2026-10-18T00:00:00Z\\tpages-deploy-123\\n'\n"
        "  fi\n"
        "else\n"
        "  while [[ $# -gt 0 ]]; do\n"
        '    if [[ $1 == -D ]]; then cp -R "$PREVIOUS_ARTIFACT/." "$2/"; exit 0; fi\n'
        "    shift\n"
        "  done\n"
        "fi\n"
    )
    gh.chmod(0o755)
    summary = tmp_path / "summary.md"
    output = tmp_path / "output.txt"
    subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", recovery["run"]],
        cwd=tmp_path,
        env={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "welkincz/advisor-pulse",
            "GH_TOKEN": "fake",
            "GITHUB_STEP_SUMMARY": str(summary),
            "GITHUB_OUTPUT": str(output),
            "RUNNER_TEMP": str(tmp_path / "runner-temp"),
            "PREVIOUS_ARTIFACT": str(previous),
            "ARTIFACT_PRESENT": str(artifact_present).lower(),
        },
        check=True,
    )
    dist = tmp_path / "web" / "dist"
    if artifact_present and run_status == "FAILED":
        assert output.read_text() == "ready=true\n"
        assert (dist / "data" / "manifest.json").read_text() == "old manifest"
        assert (dist / "data" / "weekly.parquet").read_text() == "old data"
        assert (dist / "data" / "run_log.json").read_text() == new_log
        assert not (dist / "bad-new-file").exists()
    else:
        assert not output.exists()
        assert "recovery skipped" in summary.read_text()


def test_deploys_build_the_dbt_docs_before_the_site_and_ship_without_them_on_failure() -> None:
    builds = (("weekly.yml", "Build weekly site"), ("backfill.yml", "Build backfilled site"))
    for name, build in builds:
        steps = load(name)["jobs"]["run"]["steps"]
        names = [step.get("name") for step in steps]
        docs = steps[names.index("Build dbt docs lineage")]
        assert names.index("Build dbt docs lineage") < names.index(build)
        assert "success" in docs["if"]
        assert "if ! make dbt-docs-static" in docs["run"]
        assert "rm -rf web/public/lineage" in docs["run"]
        assert docs["env"]["PULSE_DATA_DIR"] == "data"
    ci = {step.get("name"): step for step in load("ci.yml")["jobs"]["dbt"]["steps"]}
    assert ci["Static dbt docs build within budget (CI fixtures)"]["run"] == (
        "DBT_TARGET=ci make dbt-docs-static"
    )


def test_deploys_render_the_recap_video_before_the_site_and_ship_without_it_on_failure() -> None:
    builds = (
        ("weekly.yml", "Build weekly site", "steps.weekly_run.outcome == 'success'"),
        (
            "backfill.yml",
            "Build backfilled site",
            "inputs.benchmark_only != true && "
            "steps.backfill_run.outcome == 'success' && steps.backfill_run.outputs.next == ''",
        ),
    )
    for name, build, condition in builds:
        steps = load(name)["jobs"]["run"]["steps"]
        names = [step.get("name") for step in steps]
        video = steps[names.index("Render weekly recap video")]
        assert names.index("Render weekly recap video") < names.index(build)
        assert video["if"] == condition
        assert "pnpm -C video install --frozen-lockfile && make video" in video["run"]
        assert "::warning::" in video["run"]
        assert "rm -rf web/public/recap" in video["run"]


def test_pages_action_checks_the_recap_video_after_a_successful_deploy() -> None:
    by_name = {step.get("name"): step for step in action_steps()}
    deploy = by_name["Deploy successful site"]
    assert 'tee "$RUNNER_TEMP/pages-deploy.log"' in deploy["run"]
    assert 'echo "url=$url" >> "$GITHUB_OUTPUT"' in deploy["run"]
    check = by_name["Check recap video on the deployment"]
    assert check["if"] == "steps.deploy_pages.outcome == 'success'"
    assert check["env"]["DEPLOY_URL"] == "${{ steps.deploy_pages.outputs.url }}"
    assert "check_recap.sh" in check["run"]
    names = [step.get("name") for step in action_steps()]
    assert names.index("Deploy successful site") < names.index(
        "Check recap video on the deployment"
    )


def _serve(root: Path, handler_type: type) -> Any:
    import functools
    import http.server
    import threading

    handler = functools.partial(handler_type, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _check_recap(dist: Path, url: str, tmp_path: Path) -> tuple[str, str]:
    summary = tmp_path / "summary.md"
    summary.touch()
    result = subprocess.run(
        ["bash", str(PAGES_ACTION / "check_recap.sh"), str(dist), url],
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_STEP_SUMMARY": str(summary),
            "RECAP_CHECK_DELAY": "0",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout, summary.read_text()


def test_recap_check_passes_video_and_warns_on_the_spa_fallback(tmp_path: Path) -> None:
    import http.server

    class SpaFallback(http.server.SimpleHTTPRequestHandler):
        """Pages' ``/* /index.html 200``: a missing file answers as the site page."""

        def send_head(self) -> Any:
            if not Path(self.translate_path(self.path)).exists():
                self.path = "/index.html"
            return super().send_head()

        def log_message(self, *args: Any) -> None:
            pass

    dist = tmp_path / "dist"
    (dist / "recap").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>")
    (dist / "recap" / "recap.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_text("<!doctype html>")

    good = _serve(dist, SpaFallback)
    stale = _serve(served, SpaFallback)
    try:
        good_url = f"http://127.0.0.1:{good.server_address[1]}"
        stale_url = f"http://127.0.0.1:{stale.server_address[1]}/"
        stdout, summary = _check_recap(dist, good_url, tmp_path)
        assert "content-type: video/mp4" in stdout.lower()
        assert "serves video/mp4" in summary
        stdout, summary = _check_recap(dist, stale_url, tmp_path)
        assert "::warning::" in stdout
        assert "text/html" in summary and "not video/mp4" in summary
    finally:
        good.shutdown()
        stale.shutdown()


def test_recap_check_notes_a_deploy_without_the_video(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    _, summary = _check_recap(dist, "http://127.0.0.1:9", tmp_path)
    assert summary == "Recap video: not in this deploy (the page shows no recap section).\n"
    (dist / "recap").mkdir()
    (dist / "recap" / "recap.mp4").write_bytes(b"")
    stdout, summary = _check_recap(dist, "", tmp_path)
    assert "::warning::" in stdout
    assert "not checked" in summary


def test_benchmark_backfill_has_no_shared_state_or_deployment() -> None:
    workflow = load("backfill.yml")
    assert workflow["on"]["workflow_dispatch"]["inputs"]["benchmark_only"]["default"] == "false"
    steps = {s.get("name"): s for s in workflow["jobs"]["run"]["steps"]}
    env = steps["Backfill selected weeks"]["env"]
    for key in (
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "R2_ENDPOINT_URL",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        assert env[key].startswith("${{ inputs.benchmark_only != true && ")
        assert env[key].endswith(" || '' }}")
    for name in ("Build backfilled site", "Continue in a new run", "Deploy to Cloudflare Pages"):
        assert "inputs.benchmark_only != true" in steps[name]["if"]
