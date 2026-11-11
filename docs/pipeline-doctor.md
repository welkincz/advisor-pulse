# Pipeline doctor runbook

When a weekly or backfill run on `main` fails, `.github/workflows/pipeline-doctor.yml` runs Claude Code on the failed run's log and artifacts. It posts a diagnosis on the `alert:pipeline` issue and, when the cause is code, opens a draft PR on a `pipeline-fix/<run id>-<attempt>` branch. You approve what it proposes.

## How it is built

| Job | Runs | Token | What it does |
|---|---|---|---|
| `diagnose` | fixed steps, and the agent in a container | `contents: read`, `actions: read` (fixed steps only) | Collects the evidence, runs Claude Code in a locked-down container on a copy of `main` without `.git`, then packages its edits as one diff artifact. |
| `report` | fixed steps | `contents: read`, `issues: write` | Sanitises `report.md` and posts it on the open `alert:pipeline` issue (or opens one). |
| `propose` | fixed steps | `contents: write`, `pull-requests: write` | Checks the diff with `main`'s guard, applies it, checks again, pushes the branch, opens a draft PR. |

It runs only for runs whose branch is `main` in this repository. It checks out `refs/heads/main`, not the failed commit; the failed commit is used only to read its logs and to list what changed since. Each failed run attempt gets its own concurrency group, so no diagnosis is dropped. Every action is pinned to a commit SHA, and Claude Code to an exact npm version.

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

To reject a fix, close the PR and comment why on the issue. If a fix for the same workflow and failing jobs is already open as a `pipeline-fix/` draft, the doctor posts its diagnosis but opens no second PR; the patch stays in the run's `pipeline-doctor-<run id>-<attempt>` artifact for 14 days.

## Threat model

The agent reads untrusted text: logs and artifacts from a failed run can contain anything a failing test, a data file or a dependency printed. Assume that text can steer the agent (prompt injection). The tool list is not a security boundary either: the agent may run `uv run pytest`, so a test it writes can run any code. The design therefore assumes **the agent runs arbitrary code**, and gives that code nothing worth having:

- **A container, not a user account.** A second Unix user on the runner is not enough: the hosted Ubuntu image makes `/opt` and `/usr/share` world-writable, and `/opt/pipx_bin` and the tool cache are on the runner's `PATH`. Any local user can plant a fake `sudo` or `git` that the runner then executes. So the agent runs in `docker run`, with:
  - a pinned image, `node:22.21.1-bookworm`, by digest;
  - a non-root uid, a read-only root filesystem and a private `/tmp`;
  - `--cap-drop=ALL`, `no-new-privileges` and `--pids-limit 512`;
  - five folders mounted: the copy of the repo, its own home and its output folder (writable), and the evidence and the `uv` binary's folder (read-only), plus a one-line-per-user `/etc/passwd` (read-only) so the uid has a name.

  It cannot see the runner's files, `PATH`, processes, Actions runtime token or Docker socket, and there is no `sudo` inside. Containers cannot reach cloud metadata (169.254.169.254), the Azure host agent except for DNS (168.63.129.16 is also the resolver), or the runner itself (`INPUT` on `docker0` is dropped). The internet stays open, because the Claude API needs it. A fixed step removes the container (`docker rm -f`) and confirms that none is left before anything reads its output. No step after the agent calls `sudo`.
- **No GitHub token at all.** The agent's environment holds only `CLAUDE_CODE_OAUTH_TOKEN`, `HOME`, `PATH` and fixed settings, including `DISABLE_AUTOUPDATER=1`, so the pinned Claude Code version is the one that runs. Claude Code is run directly (`claude -p`), not through `claude-code-action`, which always exports a GitHub token to the agent and writes it into the git remote. The job token, read-only, is used only by the fixed evidence step, and the checkout keeps no credential (`persist-credentials: false`).
- **No git and no repo metadata.** The agent works on a copy of `main` without `.git`, so it cannot change git config, hooks or history. Its tool list allows reading, editing `src/`, `tests/`, `dbt/`, `scripts/` and its output folder (path rules are `Edit(...)` rules: Claude Code ignores `Write(path)` rules), and `uv run pytest/ruff/mypy`. It denies `git`, `gh`, `curl`, `.github/`, contracts, `/proc` and `/etc`.
- **No cache.** Nothing in the doctor saves an Actions cache (see *Cache poisoning*).
- **Fixed code decides what leaves the runner.** The package step runs once the container is confirmed gone; that check fails closed if Docker cannot be asked. It refuses if the agent swapped its folders for links, copies its edits back without `.git`, links followed or special files, and writes one diff with `--no-renames`. Its `git` calls run with the git-lfs filters off, so an agent-written `.gitattributes` triggers nothing on the host. `report` and `propose` run no agent-written code.
- **Check before write.** `propose` first checks that the base commit is on `main`. It takes `scripts/pipeline_fix_guard.py` from `origin/main` itself, never from the `diagnose` job's output, before it downloads the diff, and runs it with `python3 -I`. `report` checks the guard out from `refs/heads/main` too. The guard reads the diff with `git apply --numstat/--summary` and rejects it before anything is written if:
  - any path is outside `src/`, `tests/`, `dbt/` and `scripts/`;
  - it touches `src/pulse/contracts/`, `.github/`, `docs/PLAN.md`, `AGENTS.md`, `pyproject.toml`, a lock file, `dbt/dbt_project.yml`, `dbt/packages.yml`, `dbt/dependencies.yml` or the guard itself;
  - at any depth, it touches a file that configures git, Python, pytest or dbt: `.gitattributes`, `.gitignore`, `.gitmodules`, `.lfsconfig`, `pytest.ini`, `setup.cfg`, `setup.py`, `tox.ini`, `profiles.yml`, `sitecustomize.py`, `usercustomize.py`, `*.pth`, or a `conftest.py` outside `tests/`;
  - it adds a symlink, submodule or binary file, contains a rename or copy, or is larger than 1 MB.
  After applying, the guard checks the commit against `origin/main` again.
- **Fixed branch, token only for the push.** The branch is `pipeline-fix/<run id>-<attempt>`, built from digits only, and pushed with the explicit refspec `HEAD:refs/heads/pipeline-fix/<id>-<attempt>`, never forced. The checkout keeps no credential; the token reaches git only in the push step, through `gh auth setup-git`.
- **Text is sanitised before it is posted.** Report, PR description and commit message are scanned for token patterns and withheld if one matches. `@mentions`, `#N`, `GH-N` and issue or PR URLs get a zero-width space, so they neither notify nor backlink; `<!--` is escaped; long text is cut at a line boundary with any code fence closed. The duplicate-check marker is the PR body's first line, written by the workflow, so the agent cannot forge it.
- **Nothing merges or runs production.** No job can merge, approve, mark ready or dispatch a workflow. `main` requires CI, which a draft PR from `GITHUB_TOKEN` does not get until a person marks it ready.

### Cache poisoning

A `workflow_run` job runs in `main`'s cache scope. If the doctor saved a dependency cache, for example through `setup-uv`'s post step, under the key the weekly run restores, the next weekly run would install from it while holding the `R2_*`, `CLOUDFLARE_*`, `ALERT_WEBHOOK_URL` and `CLAUDE_CODE_OAUTH_TOKEN` secrets. Code with the Actions runtime token can write any cache key directly. Two defences:

1. **The doctor saves nothing.** `setup-uv` has `enable-cache: false` (its default, `auto`, caches on hosted runners), and the doctor has no `actions/cache`, no `setup-node` cache and no `setup-python` cache. The agent cannot reach the runtime token: it runs in a container that cannot see the runner.
2. **The jobs that hold deploy secrets restore nothing.** `weekly.yml` and `backfill.yml` set `enable-cache: false` and dropped `cache: pnpm`, so a poisoned entry written by any job on `main` is never installed next to those secrets. `ci.yml` still caches: it holds no secrets.

**Cost.** In the last successful weekly run (9 Nov) the three setup steps and the install took 19 s with warm caches (`setup-uv` 4 s, `setup-node` 5 s, install 9 s) out of about 7 minutes. Without caches, uv downloads about 650 MB of wheels and pnpm about 610 MB of packages. Locally, a cold `uv sync` took 4 s and a cold `pnpm install` 11 s. On a hosted runner, expect about 20–60 s more per run, under 15% of a weekly run and under 3% of a 30-minute backfill. This is an estimate; the first weekly run after merge gives the real figure.

### Limits

- **The OAuth token is in the agent's process.** `CLAUDE_CODE_OAUTH_TOKEN` must reach Claude Code, and the agent has network access. `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` removes it from the agent's subprocesses, best effort; the `/proc` deny rule covers the obvious read path. Code the agent runs could still find it and send it out. If it leaks, revoke it (`claude setup-token` makes a new one) and update the secret.
- **The agent can write anything into its report or PR description,** and the `pipeline-doctor-*` artifact keeps its raw output for 14 days, readable by anyone who can read the repo's Actions artifacts. The token scan catches known token formats only; a split or encoded token passes. Posted text can still make misleading claims or carry plain links. Judge it against the log.
- **The guard limits where a fix goes, not what it does.** A change under `src/` or `tests/` (including `tests/conftest.py`) can still be wrong or hostile. Nothing in the doctor runs it; CI runs it only after a person marks the PR ready, which is why you read the whole diff first.
- **Draft PRs need a repo setting.** `GITHUB_TOKEN` can open a PR only when *Settings → Actions → General → Allow GitHub Actions to create and approve pull requests* is on. It is off today. Until it is on, `propose` pushes the branch and fails with a link to open the PR by hand. Turning it on also lets workflow tokens approve PRs; `main` requires no approvals, so that adds little.
- **Duplicate fixes are matched by workflow and failing job names.** Two failures with the same jobs but different causes share one open fix. Two failures that run at the same moment can both open one.
- **The container shares the runner's kernel.** A kernel or Docker escape would reach the runner. That is the residual risk; a separate VM would close it, and GitHub-hosted runners offer none per step.
- **The container can write its own mounted folders,** including the repo copy, so a hostile edit can still reach the diff. The fixed steps only copy and read them: links are copied as links, special files are skipped, and the guard decides.
- **Checked locally, not yet on a hosted runner.** With Docker on an Apple-silicon Mac (native arm64), the container setup installed Claude Code 2.1.322 on Node 22, ran `uv sync --frozen` and ran the guard tests. Under the agent's settings, writes to `/opt`, `/usr/share`, `/usr/local/bin`, `/etc`, `/`, the evidence and the `uv` folder were blocked. Only `/work/out`, the repo copy, its home and the private `/tmp` were writable. All capabilities were 0, `NoNewPrivs` was 1, there was no `sudo` and no Docker socket, and `docker rm -f` left no container. The permission rules were checked with Claude Code 2.1.322: `Edit(src/**)` allowed `src/`, `Edit(.github/**)` and a `Read(//etc/**)` deny blocked, and an unlisted path was not written. Still unverified until the drills run: x86-64 (the hosted runner), headless login with `CLAUDE_CODE_OAUTH_TOKEN` in the container, the `iptables` rules (in particular that container DNS still works), and the cache cost above.

## Running the drills

Both need this merged (a `workflow_run` workflow runs from the default branch) and a valid `CLAUDE_CODE_OAUTH_TOKEN`.

1. **Forced fail.** Run the weekly report from the Actions tab with `force_fail` ticked. The doctor should comment that the failure was forced, name the check with its log lines, and open no PR. A drill runs the real pipeline up to the forced check, so run it when no real run is due.
2. **Planted bug.** On `main`, a run must fail from code, since the doctor ignores other branches. Merge a small, obviously wrong change behind a PR (for example, a check threshold that always fails), let the weekly run fail, and confirm the doctor opens a draft `pipeline-fix/` PR whose CI passes once marked ready. Revert the planted change whether or not the fix is right.

## What it cannot do

- **Merge, approve or mark a PR ready, or run a workflow.** No job has a command for it.
- **Push anywhere but a new `pipeline-fix/<run id>-<attempt>` branch.** Only the `propose` job pushes, with a fixed refspec, after the guard.
- **Change contracts, `.github/`, PLAN.md, AGENTS.md, `pyproject.toml`, lock files or git, pytest, Python and dbt configuration.** The guard rejects the whole patch before it is applied.
- **Read repo secrets** other than its own `CLAUDE_CODE_OAUTH_TOKEN`, or any GitHub token.

If `CLAUDE_CODE_OAUTH_TOKEN` was rejected, the doctor cannot run; the weekly alert still opens.
