# Pipeline doctor runbook

When a weekly or backfill run fails, `.github/workflows/pipeline-doctor.yml` runs Claude Code on the failed run's log and artifacts. It writes a diagnosis and, when the cause is code, a draft PR. It cannot merge, re-run production or read repo secrets. You approve what it proposes.

## Reading the diagnosis

Open the issue labelled `alert:pipeline`. The weekly alert writes the issue body: the failed stages and checks. The doctor adds a comment with these headings:

| Heading | What to check |
|---|---|
| Failing stage | It matches the alert's table. |
| Root cause | The quoted log lines prove it. Open the linked run if they don't. |
| Is a re-run safe? | It says how far the run got and whether the lock was released. |
| Proposed fix | Code means a draft PR. Anything else names who has to act. |

Treat the diagnosis as a proposal. It is an agent's reading of a log.

## Approving a fix

1. Read the draft PR's diff and test results.
2. Mark it ready for review. CI and the PR review start then, because a push from the doctor's token does not start workflows.
3. Merge it when CI is green and the review has no must-fix items.
4. Re-run the failed week yourself from the Actions tab. The doctor never does.

To reject a fix, close the PR and comment why on the issue.

## Running the drill

Run the weekly report from the Actions tab with `force_fail` ticked. The doctor should comment that the failure was forced, name the check, and open no PR. A drill runs the real pipeline up to the forced check, so run it when no real run is due.

## What it cannot do

- **Merge, approve or mark a PR ready.** Its tool list has no such command.
- **Run a workflow.** Same list.
- **Change contracts, PLAN.md or AGENTS.md.** The prompt tells it to describe such a fix and stop. The tool list does not enforce this, so check the diff.
- **Read repo secrets.** Only its own token and the job's `GITHUB_TOKEN` are passed to it.

Its own token is `CLAUDE_CODE_OAUTH_TOKEN`. If that token was rejected, the doctor cannot run; the weekly alert still opens.
