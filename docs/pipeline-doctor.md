# Pipeline doctor runbook

When a weekly or backfill run on `main` fails, `.github/workflows/pipeline-doctor.yml` runs Claude Code on the failed run's log and artifacts. It posts a diagnosis on the `alert:pipeline` issue and, when the cause is code, opens a draft PR on a `pipeline-fix/<run id>-<attempt>` branch. You approve what it proposes.

## How it is built

| Job | Runs | Token | What it does |
|---|---|---|---|
| `diagnose` | the agent, then fixed steps | `contents: read`, `actions: read` | Reads the evidence, writes `report.md`. For a code fix: edits files, then a fixed step commits them and saves a patch as an artifact. |
| `report` | fixed steps | `contents: read`, `issues: write` | Posts `report.md` on the open `alert:pipeline` issue (or opens one). |
| `propose` | fixed steps | `contents: write`, `pull-requests: write` | Applies the patch to `main`, runs the path guard, pushes the branch, opens a draft PR. |

It runs only for runs whose branch is `main` in this repository, and it checks out `main`, not the failed commit. The failed commit is used only to read its logs. Each failed run attempt gets its own concurrency group, so no diagnosis is dropped.

## Reading the diagnosis

Open the issue labelled `alert:pipeline`. The weekly alert writes the issue body: the failed stages and checks. The doctor adds a comment with these headings:

| Heading | What to check |
|---|---|
| Failing stage | It matches the alert's table. |
| Root cause | The quoted log lines prove it. Open the linked run if they don't. |
| Is a re-run safe? | It says how far the run got and whether the lock was released. |
| Proposed fix | Code means a draft PR. Anything else names who has to act. |

Treat the diagnosis as a proposal. It is an agent's reading of a log, and the log may contain text written to mislead it.

## Approving a fix

1. Read the draft PR's whole diff, not only the description. The description is the agent's own.
2. Mark it ready for review. CI and the PR review start then, because a push made with `GITHUB_TOKEN` does not start workflows.
3. Merge it when CI is green and the review has no must-fix items.
4. Re-run the failed week yourself from the Actions tab. The doctor never does.

To reject a fix, close the PR and comment why on the issue. If a fix for the same workflow and failing jobs is already open as a `pipeline-fix/` draft, the doctor posts its diagnosis but opens no second PR; the patch stays in the run's `pipeline-doctor-<run id>` artifact for 14 days.

## Threat model

The agent reads untrusted text: logs and artifacts from a failed run can contain anything a failing test, a data file or a dependency printed. Assume that text can steer the agent (prompt injection). The tool list is not a security boundary either: the agent may run `uv run pytest`, so a test it writes can run any code in its job. The design therefore assumes **the agent can run arbitrary code in the `diagnose` job**, and makes that job worth little:

- **No write token.** The job token has `contents: read` and `actions: read`. There is no `id-token: write`, so the action cannot mint a Claude GitHub App token with that app's write scopes.
- **No stored git credential from checkout.** `persist-credentials: false`. The action then puts the read-only job token in the `origin` URL, and sets it as `GITHUB_TOKEN`/`GH_TOKEN` for the agent: it always needs a token, and that is why the token is read-only. The agent's tool list has no `git push`, `git commit` or `gh`, and denies `.git/`, `.github/` and `/proc`.
- **Edits only where a fix belongs.** `Edit`/`Write` are scoped to `src/`, `tests/`, `dbt/`, `scripts/` and its own output folder. Evidence lives in `$RUNNER_TEMP`, outside the checkout, so it cannot end up in a commit.
- **Fixed code decides what leaves the runner.** `report` and `propose` run no agent-written code. `propose` copies `scripts/pipeline_fix_guard.py` from `main` before applying the patch, then rejects the patch unless every changed path (both sides of a rename) is under `src/`, `tests/`, `dbt/` or `scripts/`, outside `src/pulse/contracts/`, not a lock file, `pyproject.toml`, `dbt/dbt_project.yml`, `dbt/packages.yml` or the guard itself, and not a symlink or submodule. The branch name is built from the run id and attempt, digits only, and pushed with the explicit refspec `HEAD:refs/heads/pipeline-fix/<id>-<attempt>`, never forced. Report and patch are scanned for token patterns before they are posted.
- **Nothing merges or runs production.** No job can merge, approve, mark ready or dispatch a workflow. `main` requires CI, which a draft PR from `GITHUB_TOKEN` does not get until a person marks it ready.

### Limits

- **The OAuth token is in the agent's process.** `CLAUDE_CODE_OAUTH_TOKEN` must reach Claude Code. `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` removes it from the agent's subprocesses, best effort; the `/proc` deny rule covers the obvious read path. Code the agent runs could still find another way to it. If it leaks, revoke it (`claude setup-token` makes a new one) and update the secret.
- **The agent can write anything into its report or PR description.** The token scan catches known token formats only. The text is posted publicly, so it could contain misleading claims or links. Judge it against the log.
- **The read-only job token is readable by the agent.** It can read this public repo and its Actions logs and artifacts until the job ends. It cannot write.
- **The guard limits where a fix goes, not what it does.** A change under `src/` or `tests/` can still be wrong or hostile. That is why CI waits for a person to mark the PR ready, and why you read the diff.
- **Draft PRs need a repo setting.** `GITHUB_TOKEN` can open a PR only when *Settings → Actions → General → Allow GitHub Actions to create and approve pull requests* is on. It is off today. Until it is on, `propose` pushes the branch and fails with a link to open the PR by hand. Turning it on also lets workflow tokens approve PRs; `main` requires no approvals, so that adds little.
- **Duplicate fixes are matched by workflow and failing job names.** Two failures with the same jobs but different causes share one open fix. Two failures that run at the same moment can both open one.
- **Unverified until the drills run:** that `claude-code-action@v1` accepts a `workflow_run` event from a scheduled run (it checks the triggering actor's write access), and that Claude Code applies the path-scoped `Edit`/`Write` rules and `--disallowedTools` as described here.

## Running the drills

Both need this merged (a `workflow_run` workflow runs from the default branch) and a valid `CLAUDE_CODE_OAUTH_TOKEN`.

1. **Forced fail.** Run the weekly report from the Actions tab with `force_fail` ticked. The doctor should comment that the failure was forced, name the check with its log lines, and open no PR. A drill runs the real pipeline up to the forced check, so run it when no real run is due.
2. **Planted bug.** On `main`, a run must fail from code, since the doctor ignores other branches. Merge a small, obviously wrong change behind a PR (for example, a check threshold that always fails), let the weekly run fail, and confirm the doctor opens a draft `pipeline-fix/` PR whose CI passes once marked ready. Revert the planted change whether or not the fix is right.

## What it cannot do

- **Merge, approve or mark a PR ready, or run a workflow.** No job has a command for it.
- **Push anywhere but a new `pipeline-fix/<run id>-<attempt>` branch.** Only the `propose` job pushes, with a fixed refspec, after the guard.
- **Change contracts, `.github/`, PLAN.md, AGENTS.md, `pyproject.toml` or lock files.** The guard rejects the whole patch.
- **Read repo secrets** other than its own `CLAUDE_CODE_OAUTH_TOKEN`.

If `CLAUDE_CODE_OAUTH_TOKEN` was rejected, the doctor cannot run; the weekly alert still opens.
