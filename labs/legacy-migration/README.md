# Legacy migration lab: source-to-target parity (#324)

A small, local, synthetic exercise. One report, the **branch weekly contact report**, is written
twice: once as a deliberately old-style SQL job, and once as the existing dbt mart
(`marts.mart_org_weekly`, level `BRANCH`). A reusable harness reconciles the two on the fixture
warehouse and prints a readable mismatch report.

The legacy job is **not SAS** and was never a real or production job. It is a single procedural
SQL script written in an older style for this exercise: temp tables built step by step, nested and
correlated subqueries, and a hand-maintained calendar
([`legacy/branch_contact_report.sql`](legacy/branch_contact_report.sql)). It reads only the landed
raw tables (`raw.snowflake__activity`, `raw.teradata__advsr_asgn`) and shares no code with `dbt/`.

## Run it

```sh
make dbt-build-ci          # builds data/ci/warehouse.duckdb from fixtures/ (root project)
uv run --project labs/legacy-migration python labs/legacy-migration/run.py
uv run --project labs/legacy-migration pytest labs/legacy-migration
```

Flags: `--strict` compares without the tolerance and sentinel decisions (it shows the quirks);
`--inject-mismatch` adds 1 to one legacy count first. Exit 0 = parity, 1 = any difference,
2 = warehouse missing. The lab has its own `pyproject.toml` and `uv.lock` (DuckDB, pytest); the
root project does not depend on it, and `make check` does not run it.

## What the harness checks

[`parity.py`](parity.py) works on plain row dicts, so any source can be compared with any target:

1. **Row counts** on each side.
2. **Duplicate keys** on each side.
3. **Key-set diff**: keys missing from the source and extra in the source.
4. **Column compare** on joined keys, exact by default, with a per-column absolute tolerance
   and an optional source sentinel read as null.
5. **Report**: one line per problem, with the full key, the column, both values and the diff.

The source-to-target mapping is data, not code: [`mapping.toml`](mapping.toml) holds the key
templates, the column renames and the per-column rules.

## Legacy quirks and mapping decisions

| Quirk in the legacy job | How the harness sees it | Decision (in `mapping.toml`) |
|---|---|---|
| Q1 Branch code without prefix (`0101`) | Without D1, all 24 keys are missing and 24 are extra; nothing joins | **D1** key template `BR-{BRNCH_CD}` |
| Q2 Average meeting minutes rounded half-up to 1 dp; the mart rounds to 2 dp | 5 cells differ by at most 0.05 (e.g. 61.3 vs 61.25) | **D2** tolerance 0.05 on that column; the mart's 2-dp value stays the published figure |
| Q3 Average written as 0 when no meeting was held; the mart writes null | 1 cell, `2026-W40 / BR-0202`: 0.0 vs None | **D3** a legacy 0 is read as null. Caveat: the contract allows a 0-minute duration, so a real 0 average would also be nulled. The fixtures have none (shortest completed meeting: 30 min) |

Counts (`activities_completed`, `calls_out`, `calls_in`, `unique_clients_contacted`) have no
decision: they must match exactly.

## Measured run

Apple M4 Max, macOS 26.6.2, local, DuckDB 2.0.0 (lab lock). Input: the fixture warehouse from
`make dbt-build-ci` (654 landed activity rows and 26 assignment events; 4 ISO weeks, 6 branches).
Building that warehouse took 15.7 s wall (`PASS=537 WARN=2 ERROR=0`).

```text
$ uv run --project labs/legacy-migration python labs/legacy-migration/run.py --strict
PARITY FAIL  keys=(iso_week_id, branch_id)
  rows        source=24  target=24
  key diff    missing_in_source=0  extra_in_source=0
  duplicates  source=0  target=0
  cells       compared=120  mismatched=6
  mismatch (iso_week_id=2026-W38, branch_id=BR-0201) avg_meeting_duration_min: source=52.8 target=52.83  diff=-0.03
  mismatch (iso_week_id=2026-W38, branch_id=BR-0202) avg_meeting_duration_min: source=55.8 target=55.83  diff=-0.03
  mismatch (iso_week_id=2026-W38, branch_id=BR-0501) avg_meeting_duration_min: source=61.3 target=61.25  diff=+0.05
  mismatch (iso_week_id=2026-W40, branch_id=BR-0102) avg_meeting_duration_min: source=54.8 target=54.78  diff=+0.02
  mismatch (iso_week_id=2026-W40, branch_id=BR-0201) avg_meeting_duration_min: source=53.8 target=53.75  diff=+0.05
  mismatch (iso_week_id=2026-W40, branch_id=BR-0202) avg_meeting_duration_min: source=0.0 target=None
  timing      legacy_s=0.042  target_s=0.001  reconcile_s=0.000  total_s=0.042

$ uv run --project labs/legacy-migration python labs/legacy-migration/run.py
PARITY PASS  keys=(iso_week_id, branch_id)
  rows        source=24  target=24
  key diff    missing_in_source=0  extra_in_source=0
  duplicates  source=0  target=0
  cells       compared=120  mismatched=0
  timing      legacy_s=0.030  target_s=0.000  reconcile_s=0.000  total_s=0.031

$ uv run --project labs/legacy-migration python labs/legacy-migration/run.py --inject-mismatch
PARITY FAIL  keys=(iso_week_id, branch_id)
  ...
  cells       compared=120  mismatched=1
  mismatch (iso_week_id=2026-W39, branch_id=BR-0201) activities_completed: source=33 target=32  diff=+1
```

Five repeated default runs: 0.11–0.15 s wall per command including `uv run` start-up; the legacy
script itself took 0.032–0.046 s.

Tests (`9 passed in 0.16s`): five harness unit tests on hand-made rows (exact key and column of
an injected mismatch, missing/extra/duplicate keys, tolerance edge, sentinel) and four on the
fixture warehouse (parity after D1–D3, quirks found under `--strict`, the injected mismatch
reported as `(2026-W39, BR-0201) activities_completed`, and no key joins without D1). The
warehouse tests skip when `data/ci/warehouse.duckdb` is absent.

## Limits

- **No real SAS**, no SAS syntax, runtime or licence; the legacy side is DuckDB SQL in an old style.
- **No production cutover** and **no dual-run period**: one comparison on fixed fixtures, not
  weeks of side-by-side runs with sign-off.
- One report, five measures, 24 rows. The legacy job covers only completed activity; the mart's
  booked, held, no-show, advisor and portfolio measures are out of scope.
- The legacy job was written by the same person who knows the mart's rules, after reading them,
  so agreement on counts is weaker evidence than reconciling an independent legacy system.
- The hard-coded calendar covers 2026-W37 to W40 only, matching the fixtures.
- Local, synthetic, single machine. CI does not run these tests.
