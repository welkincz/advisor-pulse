# AGENTS.md — Advisor Pulse

Rules for every coding agent (Claude Code, Cursor) and every human working in this repo.
Read this file and `docs/PLAN.md` before starting any issue. If they disagree, PLAN.md wins on design and this file wins on process.

## 1. Ground rules

- **Synthetic only.** No real bank names, real schemas, real business rules, or real people. The bank is "Maplecrest Bank (fictional)". Public geography (StatCan FSA boundaries, province names) is fine.
- **Weekly batch, not live.** Never write "live" or "real-time" in UI copy or docs. Say "weekly report", "last weekly run".
- **Contracts first.** Schemas live in `src/pulse/contracts/`. Do not invent columns. If you need a new one, change the contract in the same PR and list it under "Contract changes" in the PR body.
- **Deterministic.** The generator is seeded. Tests must not depend on wall-clock time; inject `now` / `iso_week_id`.
- **No secrets in code, fixtures, logs, or PR text.** Read them from environment variables only.

## 2. One issue = one branch = one PR

1. **Pick** an issue labelled `status:ready` whose `agent:*` label matches you (or `agent:any`).
2. **Claim it:** assign yourself or comment `claiming` and add `status:in-progress`. Never work on an issue someone else has claimed.
3. **Branch** from latest `main`: `<area>/<issue#>-<short-slug>`, e.g. `ingest/16-activity-incremental`. Use a git worktree when running agents in parallel on one machine.
4. **Stay inside the issue's "Owns" paths.** Touching anything else needs a note in the PR explaining why. Shared files (see §4) need their own issue.
5. **Open a PR** titled `<type>(<area>): <summary> (#<issue>)`, with body `Closes #<issue>` and the template filled in.
6. **Keep PRs small:** under ~400 changed lines excluding generated files and fixtures. If an issue grows beyond that, split it and say so on the issue.
7. **Do not merge your own PR** (Cursor included). Claude reviews every PR and squash-merges it when CI is green and there are no must-fix items, then deletes the branch. PRs that change `src/pulse/contracts/`, PLAN.md design, or add a dependency also wait for the human owner's OK.
8. **Automatic review.** The `pr-review.yml` workflow runs Claude Code on every non-draft PR (up to 2 automatic reviews per PR). To request a re-review, comment `@claude review`. PRs labelled `skip-review` are excluded. The review checks the §9 checklist and the linked issue's acceptance criteria. Claude comments only — it never approves, merges, or pushes.

Commit messages: Conventional Commits (`feat`, `fix`, `test`, `docs`, `chore`, `refactor`, `ci`), imperative mood.

## 3. Definition of done

An issue is done only when **all** of these hold:

- [ ] Every acceptance criterion in the issue is met, and the PR body shows how (command output or screenshot).
- [ ] `make check` passes locally (lint + types + unit tests + contracts).
- [ ] New logic has tests. Data logic is tested against `fixtures/`, not hand-written expectations alone.
- [ ] dbt changes: `make dbt-build-ci` passes; every new model has a `.yml` with description, column descriptions, and tests; mart models have `contract: {enforced: true}`.
- [ ] Web changes: `make web-check` passes; works at 375 px width; keyboard reachable; respects `prefers-reduced-motion`; light and dark both checked.
- [ ] Docs updated if behavior, a contract, a KPI, or a DQ rule changed (PLAN.md §6–§8 are the source of truth).
- [ ] No TODOs without a linked follow-up issue.

## 4. Ownership and shared files

| Path | Owner lane | Notes |
|------|-----------|-------|
| `src/pulse/contracts/` | contracts (Claude) | Changes need review by the contracts owner |
| `src/pulse/generate/` | data-gen | |
| `src/pulse/ingest/` | ingest | |
| `src/pulse/quality/`, `runner/`, `state/` | orchestration | |
| `src/pulse/export/` | export | |
| `src/pulse/narrative/` | ai | |
| `dbt/models/staging/` | dbt | One `.yml` per model, never a shared `schema.yml` |
| `dbt/models/intermediate/`, `marts/` | dbt | Same |
| `geo/`, `web/public/geo/` | geo | |
| `web/src/features/<name>/` | frontend, one feature per issue | |
| `web/src/theme/`, `web/src/data/` | frontend core (Claude) | |
| `fixtures/` | contracts | Regenerate with `make fixtures`; never hand-edit Parquet |
| `.github/workflows/` | orchestration | |

**Shared files (change only in a dedicated issue, or with a one-line justification in the PR):**
`pyproject.toml`, `uv.lock`, `web/package.json`, `web/pnpm-lock.yaml`, `dbt/dbt_project.yml`, `Makefile`, `AGENTS.md`, `docs/PLAN.md`.
If you need a new dependency, say so in the PR body under "Dependencies added", with the reason.

## 5. Running locally

Prerequisites: Python 3.12, `uv`, Node 22, `pnpm`, DuckDB CLI (optional).

```bash
make setup           # uv sync + pnpm install + dbt deps
make fixtures        # regenerate tiny deterministic fixtures
make check           # ruff + mypy + pytest -m "not slow" + contracts check
make generate WEEKS=8
make run WEEK=2026-W40       # one weekly run end to end, local state in data/
make backfill FROM=2026-W01 TO=2026-W40
make dbt-build-ci    # dbt build against fixtures
make dbt-docs        # dbt docs generate + serve
make web-dev         # Vite dev server on fixtures (an Ontario and Quebec slice)
make web-dev-latest  # Vite dev server on the latest weekly export: all regions (needs gh)
make web-check       # lint + typecheck + build + Playwright smoke
make export          # marts -> web/public/data
```

Environment variables (`.env.example`): `PULSE_DATA_DIR`, `PULSE_SEED`, `PULSE_NARRATIVE_MODEL`, `ANTHROPIC_API_KEY`, `R2_*`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GSHEET_ID`. Everything except `PULSE_*` is optional locally. Code paths that need a secret must skip cleanly when it is absent.

## 6. Testing conventions

- `pytest` markers: `unit` (default), `integration` (DuckDB on fixtures), `slow` (multi-week generation), `live` (calls external APIs; never runs in CI by default).
- Data tests assert against the generator's **defect manifest**: what was injected must be exactly what was caught.
- Idempotency tests run the same week twice and compare row counts and mart content hashes.
- Frontend: Vitest for data hooks and utilities; Playwright smoke for each route. Visual changes need before/after screenshots in the PR.

## 7. Tool routing

| Tool | Take issues labelled | Good at here |
|------|---------------------|--------------|
| Claude Code | `agent:claude` | Contracts, SCD2 and attribution logic, runner and failure handling, AI narrative and guardrails, data layer, design direction, integration, PR review |
| Cursor | `agent:cursor` | Most implementation: dbt staging and marts, React features, charts, map, workflows, geo scripts, loaders, export, docs |
| Human | `agent:human` | Accounts, secrets, DNS, Tableau publishing, final copy approval |

Labels are a default, not a lock. Any agent can take an `agent:any` issue.
Before starting, every agent must read: this file, the issue, the contracts it depends on, and the "Owns" paths.

## 8. Dependencies and status labels

- Issue bodies list `Depends on: #a, #b`. The `deps.yml` workflow moves an issue from `status:blocked` to `status:ready` when all of its dependencies are closed.
- If you find a hidden dependency, add it to the issue body and set `status:blocked`. Do not work around it with a stub unless the issue says to.
- Work against **fixtures** whenever upstream code is not merged yet. That is what they are for.

## 9. Review checklist (for Claude when reviewing PRs)

> Automated by `.github/workflows/pr-review.yml` using the prompt in `.github/review-prompt.md`. See §2 step 8.

- Matches the contract, with no silent column or type changes.
- Idempotent and deterministic; no wall-clock dependencies.
- Failure paths handled and logged to `run_log` with a clear message.
- Tests cover the acceptance criteria, including at least one failure case.
- Changes stay within the issue's "Owns" paths; shared files are untouched or justified.
- UI: tokens only (no raw hex), reduced-motion respected, no "live" copy.
