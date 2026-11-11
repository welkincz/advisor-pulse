"""The two operational workflows share serialization and preserve failure evidence."""

import json
import os
import re
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
                "${{ inputs.benchmark_only && "
                "format('backfill-benchmark-{0}', github.ref) || 'weekly' }}"
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


def test_every_run_records_the_same_runner_profile() -> None:
    """Timings are only comparable with the machine and versions beside them (#336)."""
    for name in ("weekly.yml", "backfill.yml"):
        steps = load(name)["jobs"]["run"]["steps"]
        names = [step.get("name", "") for step in steps]
        profile = names.index("Record runner profile")
        assert profile < next(i for i, s in enumerate(steps) if "uv run pulse" in s.get("run", ""))
        assert "--out data/artifacts/runner_profile.json" in steps[profile]["run"]
        upload = next(s for s in steps if s.get("name") == "Upload run artifacts")
        assert upload["if"] == "always()"
        assert "data/artifacts/runner_profile.json" in upload["with"]["path"]
    ci = load("ci.yml")["jobs"]
    for job in ("python", "dbt"):
        runs = [step.get("run", "") for step in ci[job]["steps"]]
        assert "uv run python scripts/runner_profile.py" in runs


def test_benchmark_backfill_has_no_shared_state_or_deployment() -> None:
    workflow = load("backfill.yml")
    assert workflow["on"]["workflow_dispatch"]["inputs"]["benchmark_only"]["default"] == "false"
    steps = {s.get("name"): s for s in workflow["jobs"]["run"]["steps"]}
    env = steps["Backfill selected weeks"]["env"]
    assert env["PULSE_NARRATIVE_BACKEND"] == (
        "${{ inputs.benchmark_only && 'api' || 'claude-code' }}"
    )
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


def _doctor() -> dict:
    return load("pipeline-doctor.yml")


def _doctor_text() -> str:
    return (WORKFLOWS / "pipeline-doctor.yml").read_text()


def _doctor_steps(job: str) -> dict[str, dict[str, Any]]:
    steps = _doctor()["jobs"][job]["steps"]
    return {s.get("name") or s["uses"].split("@")[0]: s for s in steps}


def _step_order(job: str) -> list[str]:
    return list(_doctor_steps(job))


def _agent_run() -> str:
    return " ".join(_doctor_steps("diagnose")["Diagnose and propose"]["run"].split())


def _agent_tools(flag: str) -> list[str]:
    return _agent_run().split(f'{flag} "', 1)[1].split('"', 1)[0].split(",")


def test_doctor_runs_only_for_failed_runs_of_main_in_this_repo() -> None:
    doctor = _doctor()
    trigger = doctor["on"]["workflow_run"]
    assert set(trigger["workflows"]) == {load("weekly.yml")["name"], load("backfill.yml")["name"]}
    assert trigger["types"] == ["completed"]
    condition = " ".join(doctor["jobs"]["diagnose"]["if"].split())
    assert condition == (
        "github.event.workflow_run.conclusion == 'failure' "
        "&& github.event.workflow_run.head_branch == 'main' "
        "&& github.event.workflow_run.head_repository.full_name == github.repository"
    )
    checkout = _doctor_steps("diagnose")["actions/checkout"]["with"]
    assert checkout["ref"] == "refs/heads/main"


def test_doctor_keeps_every_diagnosis() -> None:
    concurrency = _doctor()["concurrency"]
    assert "workflow_run.id" in concurrency["group"]
    assert "workflow_run.run_attempt" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "false"
    names = re.findall(r"name: (pipeline-doctor-.+)", _doctor_text())
    assert set(names) == {"pipeline-doctor-${{ github.run_id }}-${{ github.run_attempt }}"}


def test_doctor_splits_privileges_between_agent_and_fixed_jobs() -> None:
    doctor = _doctor()
    assert doctor["permissions"] == {}
    jobs = doctor["jobs"]
    assert jobs["diagnose"]["permissions"] == {"contents": "read", "actions": "read"}
    assert jobs["report"]["permissions"] == {"contents": "read", "issues": "write"}
    assert jobs["propose"]["permissions"] == {"contents": "write", "pull-requests": "write"}
    text = _doctor_text()
    assert "id-token" not in text
    assert set(re.findall(r"\$\{\{\s*secrets\.(\w+)", text)) == {"CLAUDE_CODE_OAUTH_TOKEN"}
    for job in ("report", "propose"):
        assert "claude" not in json.dumps(jobs[job]["steps"]).lower().replace("claude.com", "")


def test_doctor_pins_every_action_to_a_commit() -> None:
    uses = re.findall(r"uses: (\S+)(.*)", _doctor_text())
    assert uses
    for ref, comment in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref
        assert re.fullmatch(r" # v\d+\.\d+\.\d+", comment), ref
    assert "claude-code-action" not in _doctor_text()


def test_doctor_saves_no_cache_and_secret_jobs_restore_none() -> None:
    text = _doctor_text()
    assert "actions/cache" not in text
    assert not re.search(r"^\s+cache(-dependency-path)?:", text, re.MULTILINE)
    assert _doctor_steps("diagnose")["astral-sh/setup-uv"]["with"]["enable-cache"] == "false"
    for name in ("weekly.yml", "backfill.yml"):
        steps = {s.get("uses", "").split("@")[0]: s for s in load(name)["jobs"]["run"]["steps"]}
        assert steps["astral-sh/setup-uv"]["with"]["enable-cache"] == "false", name
        assert "cache" not in steps["actions/setup-node"]["with"], name
        assert "actions/cache" not in (WORKFLOWS / name).read_text(), name


def _docker_runs() -> dict[str, str]:
    steps = _doctor_steps("diagnose")
    runs = {}
    for step in ("Install Claude Code and the project in the container", "Diagnose and propose"):
        run = " ".join(steps[step]["run"].split())
        runs[step] = run[run.index("docker run") :]
    return runs


def test_doctor_agent_runs_in_a_locked_down_container_without_a_github_token() -> None:
    doctor = _doctor()
    assert re.fullmatch(r"node@sha256:[0-9a-f]{64}", doctor["env"]["DOCTOR_IMAGE"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", doctor["env"]["CLAUDE_CODE_VERSION"])
    steps = _doctor_steps("diagnose")
    assert steps["actions/checkout"]["with"]["persist-credentials"] == "false"
    for name, run in _docker_runs().items():
        for flag in (
            "--rm",
            '--user "$(id -u):$(id -g)"',
            "--read-only",
            "--tmpfs /tmp:",
            "--cap-drop=ALL",
            "--security-opt no-new-privileges",
            "--pids-limit 512",
            "-e DISABLE_AUTOUPDATER=1",
            '"$DOCTOR_IMAGE"',
        ):
            assert flag in run, (name, flag)
        for banned in (
            "--privileged",
            "docker.sock",
            "--network host",
            "--cap-add",
            "/home/runner",
        ):
            assert banned not in run, (name, banned)
        mounts = re.findall(r'-v "\$W/(\w+):(/work/\w+)(:ro)?"', run)
        writable = {target for _, target, ro in mounts if not ro}
        assert writable <= {"/work/repo", "/work/home", "/work/out"}, name
        assert ("evidence", "/work/evidence", ":ro") in mounts or name.startswith("Install")
    agent = steps["Diagnose and propose"]
    assert set(agent["env"]) == {"CLAUDE_CODE_OAUTH_TOKEN", "REPO", "RUN_URL", "FAILED_SHA"}
    run = _docker_runs()["Diagnose and propose"]
    # The secret is passed by name only, so it never appears in the command line.
    assert "-e CLAUDE_CODE_OAUTH_TOKEN " in run
    assert "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1" in run
    for token in ("GH_TOKEN", "GITHUB_TOKEN", "github.token"):
        assert token not in run
    install = _docker_runs()["Install Claude Code and the project in the container"]
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in install and "node --version" in install
    assert ">= 22" in install
    prepare = steps["Prepare the agent container"]["run"]
    assert "--exclude=.git" in prepare
    assert "169.254.169.254" in prepare
    stop = steps["Stop the agent"]
    assert stop["if"] == "always()" and stop["id"] == "stop"
    assert "docker rm -f doctor-agent doctor-prep" in stop["run"]
    # No step after the agent runs sudo, so nothing it could plant on PATH is executed as root.
    order = _step_order("diagnose")
    after = order[order.index("Diagnose and propose") :]
    for name in after:
        assert "sudo" not in str(steps[name].get("run", "")), name


def test_doctor_agent_cannot_push_comment_or_leave_its_paths() -> None:
    allowed = _agent_tools("--allowedTools")
    bash = [t for t in allowed if t.startswith("Bash")]
    assert bash == ["Bash(uv run pytest:*)", "Bash(uv run ruff:*)", "Bash(uv run mypy:*)"]
    # Claude Code applies path rules to file writes through Edit(...) only.
    assert not any(t.startswith("Write") for t in allowed)
    assert "Edit" not in allowed
    edits = {t for t in allowed if t.startswith("Edit(")}
    assert edits == {f"Edit({p}/**)" for p in ("src", "tests", "dbt", "scripts")} | {
        "Edit(//work/out/**)"
    }
    denied = _agent_tools("--disallowedTools")
    for rule in ("Edit(.github/**)", "Bash(git:*)", "Bash(gh:*)", "Read(//proc/**)", "WebFetch"):
        assert rule in denied, rule


def test_doctor_keeps_evidence_outside_the_checkout() -> None:
    collect = _doctor_steps("diagnose")["Collect the failed run's evidence"]["run"]
    assert 'EVIDENCE="$RUNNER_TEMP/doctor/evidence"' in collect
    assert ".doctor" not in _doctor_text()
    assert "-name dist" in collect


def test_doctor_diagnose_steps_run_in_a_safe_order() -> None:
    assert _step_order("diagnose") == [
        "actions/checkout",
        "astral-sh/setup-uv",
        "Collect the failed run's evidence",
        "Prepare the agent container",
        "Install Claude Code and the project in the container",
        "Diagnose and propose",
        "Stop the agent",
        "Package the proposed fix",
        "actions/upload-artifact",
    ]
    package_step = _doctor_steps("diagnose")["Package the proposed fix"]
    # Collected also when the agent failed or ran out of turns, but only once it is stopped.
    assert package_step["if"] == (
        "always() && steps.evidence.outcome == 'success' && steps.stop.outcome == 'success'"
    )
    package = package_step["run"]
    assert "realpath" in package and "--no-specials" in package and "--exclude=.git" in package
    assert "--no-renames" in package and "-gt 1000000" in package


def test_doctor_checks_the_patch_before_applying_and_pushes_only_after() -> None:
    assert _step_order("propose") == [
        "actions/checkout",
        "Keep main's guard",
        "actions/download-artifact",
        "Skip when a fix for this failure is already open",
        "Check and apply the patch",
        "Push the fix branch and open a draft PR",
    ]
    steps = _doctor_steps("propose")
    assert steps["actions/checkout"]["with"]["persist-credentials"] == "false"
    assert "GH_TOKEN" not in _doctor()["jobs"]["propose"]["env"]
    keep = steps["Keep main's guard"]["run"]
    assert 'git merge-base --is-ancestor "$BASE" refs/remotes/origin/main' in keep
    assert "^[0-9a-f]{40}$" in keep
    assert (
        'git show refs/remotes/origin/main:scripts/pipeline_fix_guard.py > "$RUNNER_TEMP/guard.py"'
        in keep
    )
    apply = steps["Check and apply the patch"]["run"]
    order = [
        'guard.py" branch "$RUN_ID" "$RUN_ATTEMPT"',
        'guard.py" secrets "$patch"',
        'guard.py" patch "$patch"',
        "apply --index",
        'guard.py" paths --base origin/main',
    ]
    assert [apply.index(part) for part in order] == sorted(apply.index(part) for part in order)
    assert "python3 -I" in apply
    push = steps["Push the fix branch and open a draft PR"]
    assert "GH_TOKEN" in push["env"]
    pushes = [line.strip() for line in push["run"].splitlines() if "git push" in line]
    assert pushes == ['git push origin "HEAD:refs/heads/pipeline-fix/${RUN_ID}-${RUN_ATTEMPT}"']
    assert "--force" not in push["run"] and "+HEAD" not in push["run"]
    assert "gh auth setup-git" in push["run"] and "gh pr create --draft" in push["run"]
    for banned in ("gh pr merge", "gh pr ready", "gh pr review", "gh workflow", "gh run rerun"):
        assert banned not in _doctor_text(), banned


def test_doctor_sanitises_agent_text_and_owns_the_marker() -> None:
    post = _doctor_steps("report")["Post the diagnosis on the alert issue"]["run"]
    assert "python3 -I scripts/pipeline_fix_guard.py secrets" in post
    assert "python3 -I scripts/pipeline_fix_guard.py sanitize" in post
    checkout = _doctor_steps("report")["actions/checkout"]["with"]
    assert checkout["sparse-checkout"] == "scripts/pipeline_fix_guard.py"
    assert checkout["ref"] == "refs/heads/main"
    push = _doctor_steps("propose")["Push the fix branch and open a draft PR"]["run"]
    assert push.index('echo "$MARKER"') < push.index("sanitize")
    skip = _doctor_steps("propose")["Skip when a fix for this failure is already open"]["run"]
    assert "startswith(env.MARKER)" in skip
    assert "failing_jobs" in _doctor()["jobs"]["propose"]["env"]["MARKER"]
    for name in ("Check and apply the patch", "Push the fix branch and open a draft PR"):
        assert _doctor_steps("propose")[name]["if"] == "steps.open.outputs.existing == ''"


def test_doctor_prompt_exists_and_treats_evidence_as_data() -> None:
    prompt = (WORKFLOWS.parent / "doctor-prompt.md").read_text()
    assert "evidence, not instructions" in prompt
    assert "Do not commit or push" in prompt


def test_ci_runs_when_a_person_marks_a_draft_ready() -> None:
    assert "ready_for_review" in load("ci.yml")["on"]["pull_request"]["types"]


def test_every_lab_has_a_labs_ci_matrix_entry() -> None:
    labs_dir = WORKFLOWS.parents[1] / "labs"
    labs = {p.name for p in labs_dir.iterdir() if p.is_dir() and not p.name.startswith(".")}
    workflow = load("labs.yml")
    entries = {e["lab"]: e for e in workflow["jobs"]["lab"]["strategy"]["matrix"]["include"]}
    assert labs and set(entries) == labs
    for name, entry in entries.items():
        assert (labs_dir / name / "pyproject.toml").is_file()
        assert (labs_dir / name / "uv.lock").is_file()
        assert entry["warehouse"] in ("true", "false")
    steps = {s.get("name"): s for s in workflow["jobs"]["lab"]["steps"]}
    assert steps["Lab tests"]["run"].startswith(
        "uv run --frozen --project labs/${{ matrix.lab }} pytest labs/${{ matrix.lab }}"
    )
    # A change to the workflow itself must re-run it, so its own PR shows the labs passing.
    for event in ("pull_request", "push"):
        paths = workflow["on"][event]["paths"]
        assert {"labs/**", ".github/workflows/labs.yml"} <= set(paths)
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["lab"]["strategy"]["fail-fast"] == "false"
