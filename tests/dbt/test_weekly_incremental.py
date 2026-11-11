"""Weekly incremental models equal a full refresh, and change with their definition (#304).

Every incremental model is found in dbt's manifest, so a new one is covered without editing
this file. On the fixtures: load sources through W39 (activity extracts and CLNT deltas by
date) and build with the runner's dbt stage, then load W40 (rows one to three weeks late,
client reassignments and moves) and build again. Each model must match a full refresh, a
second run of the same week must change nothing, and the run must really be incremental.

The rebuild floor is the earlier of "four weeks before the newest week" and "the earliest
day of any row loaded since the last stamped build" (dbt/macros/weekly_incremental.sql), so
with no lookback at all the runner still catches the late rows; a plain ``dbt build``
without the runner's stamps does not, which shows the comparison can fail. A table stamped
with another definition, or holding a week no longer reported, is rebuilt in full.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pulse.contracts.enums import RunType, StageStatus
from pulse.ingest.stage import SOURCES_DIR, ingest
from pulse.runner import refresh, stages
from pulse.runner.stage import StageContext, StageResult
from pulse.warehouse import WAREHOUSE_FILE, connect

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "fixtures" / "sources"
DBT_DIR = ROOT / "dbt"
W39 = ("2026-W39", "2026-09-27", datetime(2026, 9, 28, 3, 30, tzinfo=UTC))
W40 = ("2026-W40", "2026-10-04", datetime(2026, 10, 5, 3, 30, tzinfo=UTC))
NO_LOOKBACK = ("--vars", "{weekly_lookback_weeks: 0}")
pytestmark = pytest.mark.integration

Hashes = dict[str, tuple[int, int]]


class _Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at

    def sleep(self, seconds: float) -> None:
        pass


def _ctx(data_dir: Path, week: tuple[str, str, datetime]) -> StageContext:
    return StageContext(f"test-{week[0]}", RunType.MANUAL, week[0], data_dir, _Clock(week[2]))


def _stage_sources(sources: Path, through: str) -> None:
    """Fixture extracts and CLNT deltas dated up to and including `through`, copied (the
    loaders' rglob does not follow symlinks), so each week's client changes arrive with it."""
    activity = sources / "snowflake" / "activity"
    activity.mkdir(parents=True, exist_ok=True)
    for partition in sorted((FIXTURES / "snowflake" / "activity").iterdir()):
        target = activity / partition.name
        if partition.name <= f"extract_date={through}" and not target.exists():
            shutil.copytree(partition, target)
    teradata = sources / "teradata"
    teradata.mkdir(exist_ok=True)
    day = through.replace("-", "")
    for path in sorted((FIXTURES / "teradata").iterdir()):
        dated = re.fullmatch(r"client_(\d{8})\.csv", path.name)
        if (dated is None or dated.group(1) <= day) and not (teradata / path.name).exists():
            shutil.copy2(path, teradata / path.name)


def _load(data_dir: Path, week: tuple[str, str, datetime]) -> None:
    _stage_sources(data_dir / SOURCES_DIR, through=week[1])
    result = ingest(_ctx(data_dir, week))
    assert result.status is not StageStatus.FAILED, result.message


def _models_only(*extra: str) -> stages.DbtCommand:
    """The runner's build command, without the data tests: they are dbt-build-ci's job."""

    def command(ctx: StageContext, target_path: Path) -> Sequence[str]:
        return [
            *stages.dbt_command(ctx, target_path),
            "--resource-type",
            "seed",
            "--resource-type",
            "model",
            *extra,
        ]

    return command


def _build(data_dir: Path, *extra: str) -> StageResult:
    """The runner's dbt stage: refresh check, build, stamps."""
    result = stages.dbt_build(_ctx(data_dir, W40), command=_models_only(*extra))
    assert result.status is not StageStatus.FAILED, result.message
    return result


def _plain_dbt(data_dir: Path, *args: str) -> None:
    """``dbt build`` without the runner: no refresh check and no stamps."""
    command = [
        *stages.dbt_command(_ctx(data_dir, W40), data_dir / "plain-target"),
        "--resource-type",
        "seed",
        "--resource-type",
        "model",
        *args,
    ]
    env = {**os.environ, "PULSE_DATA_DIR": str(data_dir)}
    proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout[-3000:]


def _incremental(data_dir: Path, target: str = stages.DBT_TARGET_DIR) -> dict[str, str]:
    """Model name -> schema, for every incremental model."""
    manifest = json.loads((data_dir / target / "manifest.json").read_text())
    models = {
        m.name: m.schema for m in refresh.incremental_models(manifest, DBT_DIR / "dbt_project.yml")
    }
    assert len(models) >= 10, models  # nine replace_from models and fct_activity
    return models


def _hashes(data_dir: Path, models: dict[str, str]) -> Hashes:
    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    try:
        return {
            name: con.execute(
                f"select count(*), coalesce(sum(hash(t)::hugeint), 0) from {schema}.{name} as t"
            ).fetchone()  # type: ignore[misc]
            for name, schema in models.items()
        }
    finally:
        con.close()


def _floors(data_dir: Path, target: str = stages.DBT_TARGET_DIR) -> dict[str, str | None]:
    """Where each replace_from model's last run deleted from; None when it was built anew."""
    floors: dict[str, str | None] = {}
    for path in (data_dir / target / "run").rglob("*.sql"):
        match = re.search(r"where \w+ >= '([^']*)';", path.read_text())
        floors[path.stem] = match.group(1) if match else None
    return floors


def _execute(data_dir: Path, sql: str) -> None:
    con = connect(data_dir / WAREHOUSE_FILE)
    try:
        con.execute(sql)
    finally:
        con.close()


@pytest.fixture(scope="module")
def built_through_w39(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A warehouse built and stamped by the runner through W39, before W40 arrives."""
    data_dir = tmp_path_factory.mktemp("w39")
    _load(data_dir, W39)
    _build(data_dir)
    return data_dir


def _with_w40(built: Path, tmp_path: Path) -> Path:
    """A copy of the W39 state with the W40 extract and client deltas loaded."""
    data_dir = tmp_path / "data"
    shutil.copytree(built, data_dir)
    _load(data_dir, W40)
    return data_dir


def _full_refresh(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> StageResult:
    with monkeypatch.context() as patched:
        patched.setenv(stages.FULL_REFRESH_ENV, "1")
        return _build(data_dir)


def test_incremental_run_equals_full_refresh_and_a_rerun_changes_nothing(
    built_through_w39: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _with_w40(built_through_w39, tmp_path)
    result = _build(data_dir)
    models = _incremental(data_dir)
    floors = _floors(data_dir)
    incremental = _hashes(data_dir, models)

    assert "Rebuilt in full" not in (result.message or "")
    # Every replace_from model deleted from a week, not from the beginning (''); the book's
    # history starts in 2026-W01, so its earlier weeks were kept, not recomputed.
    replace_from = sorted(n for n in models if n != "fct_activity")
    assert all(floors[n] for n in replace_from), floors
    assert floors["int_client_book_weekly"] > "2026-W01"
    assert floors["mart_org_quarterly"] == "FY26-Q4"

    _build(data_dir)  # the same week again
    assert _hashes(data_dir, models) == incremental

    assert "Full refresh requested" in (_full_refresh(data_dir, monkeypatch).message or "")
    assert _hashes(data_dir, models) == incremental


def test_rows_loaded_since_the_last_build_set_the_floor_without_any_lookback(
    built_through_w39: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the lookback at zero the floor would be W39 and miss the late rows of W37 and
    W38; the runner's stamp reaches back to the earliest row W40 loaded, as it would for a
    past-range backfill or history extended earlier."""
    data_dir = _with_w40(built_through_w39, tmp_path)
    _build(data_dir, *NO_LOOKBACK)
    models = _incremental(data_dir)
    floors = _floors(data_dir)
    assert floors["mart_org_weekly"] is not None and floors["mart_org_weekly"] < "2026-W38"
    stamped = _hashes(data_dir, models)

    _full_refresh(data_dir, monkeypatch)
    assert stamped == _hashes(data_dir, models)


def test_without_the_runner_and_its_stamps_a_short_lookback_misses_late_rows(
    built_through_w39: Path, tmp_path: Path
) -> None:
    """The comparison can fail: plain dbt has no stamp to read, so no lookback means the
    late rows' weeks stay stale. The late-row test warns about exactly these rows."""
    data_dir = _with_w40(built_through_w39, tmp_path)
    con = connect(data_dir / WAREHOUSE_FILE)
    try:
        for (schema, table), _ in refresh.read_stamps(con).items():
            if schema in {"intermediate", "marts"}:
                con.execute(f'comment on table "{schema}"."{table}" is null')
    finally:
        con.close()
    _plain_dbt(data_dir, *NO_LOOKBACK)
    models = _incremental(data_dir, "plain-target")
    short = _hashes(data_dir, models)

    _plain_dbt(data_dir, "--full-refresh")
    full = _hashes(data_dir, models)
    assert short["mart_org_weekly"] != full["mart_org_weekly"]
    assert short["int_kpi_events"] != full["int_kpi_events"]

    command = [
        *stages.dbt_command(_ctx(data_dir, W40), data_dir / "plain-target"),
        "--select",
        "assert_late_rows_within_lookback",
        *NO_LOOKBACK,
    ]
    command[command.index("build")] = "test"
    env = {**os.environ, "PULSE_DATA_DIR": str(data_dir)}
    proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout[-3000:]
    assert "WARN" in proc.stdout and "assert_late_rows_within_lookback" in proc.stdout


def test_a_changed_definition_rebuilds_that_model_in_full_and_only_that(
    built_through_w39: Path, tmp_path: Path
) -> None:
    """A stamp from another definition stands for a merged change to the model's SQL: the
    runner drops the table, dbt builds it from all history, and stale old weeks go. Models
    whose stamp matches stay incremental."""
    data_dir = _with_w40(built_through_w39, tmp_path)
    _build(data_dir)
    models = _incremental(data_dir)
    expected = _hashes(data_dir, models)

    old = json.dumps({refresh.STAMP_KEY: "an older definition", "loaded_through": None})
    _execute(
        data_dir,
        "update marts.mart_org_weekly set calls_out = calls_out + 1 where iso_week_id = '2026-W37';"
        f"comment on table marts.mart_org_weekly is '{old}'",
    )
    result = _build(data_dir)
    assert "Rebuilt in full after a definition change: mart_org_weekly." in (result.message or "")
    floors = _floors(data_dir)
    assert floors["mart_org_weekly"] is None  # created, not deleted from
    assert floors["mart_advisor_weekly"]  # unchanged definition: still incremental
    assert _hashes(data_dir, models) == expected

    again = _build(data_dir)  # stamped again: the next run is incremental
    assert "Rebuilt in full" not in (again.message or "")
    assert _floors(data_dir)["mart_org_weekly"]


def test_a_week_no_longer_reported_rebuilds_the_mart_from_the_start(
    built_through_w39: Path, tmp_path: Path
) -> None:
    """The full-rebuild branch of incremental_floor(): a mart holding a week before the first
    reported one (a history that reached its first full year) is rebuilt from ''."""
    data_dir = _with_w40(built_through_w39, tmp_path)
    _build(data_dir)
    models = _incremental(data_dir)
    expected = _hashes(data_dir, models)

    _execute(
        data_dir,
        "insert into marts.mart_org_weekly"
        " select * replace ('2026-W01' as iso_week_id) from marts.mart_org_weekly"
        " where iso_week_id = '2026-W37'",
    )
    _build(data_dir)
    assert _floors(data_dir)["mart_org_weekly"] == ""
    assert _hashes(data_dir, models) == expected


def test_fingerprint_follows_a_model_and_everything_downstream_of_it(
    built_through_w39: Path,
) -> None:
    manifest = json.loads((built_through_w39 / stages.DBT_TARGET_DIR / "manifest.json").read_text())
    project = DBT_DIR / "dbt_project.yml"
    before = {m.name: m.fingerprint for m in refresh.incremental_models(manifest, project)}
    assert before == {m.name: m.fingerprint for m in refresh.incremental_models(manifest, project)}

    node = manifest["nodes"]["model.advisor_pulse.int_client_book_weekly"]
    node["checksum"]["checksum"] = "changed"
    node["description"] = "a docs edit alone changes nothing"
    after = {m.name: m.fingerprint for m in refresh.incremental_models(manifest, project)}
    changed = {name for name in before if before[name] != after[name]}
    assert changed == {
        "int_client_book_weekly",
        "int_client_contact_12m",
        "int_kpi_events",
        "mart_advisor_weekly",
        "mart_geo_weekly",
        "mart_org_quarterly",
        "mart_org_weekly",
        "mart_portfolio_weekly",
        "mart_weekly_report",
    }

    macro = manifest["macros"]["macro.advisor_pulse.incremental_floor"]
    macro["macro_sql"] += " "
    moved = {m.name: m.fingerprint for m in refresh.incremental_models(manifest, project)}
    assert {n for n in moved if moved[n] != after[n]} == changed  # not fct_activity
