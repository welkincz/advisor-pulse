"""Weekly incremental models equal a full refresh, and change with their definition (#304).

Every incremental model is found in dbt's manifest, so a new one is covered without editing
this file. On the fixtures: load sources through W39 (activity extracts and CLNT deltas by
date) and build with the runner's dbt stage, then load W40 (rows one to three weeks late,
client reassignments and moves) and build again. Each model must match a full refresh, a
second run of the same week must change nothing, and the run must really be incremental.

The rebuild floor is the earlier of "four weeks before the newest week" and "the earliest
day of any row loaded since the last stamped build" (dbt/macros/weekly_incremental.sql), so
with no lookback at all the runner still catches the late rows, and a watermark that hides
them shows the comparison can fail. A table stamped with another definition (except
fct_activity, which warns), one never stamped, or one holding a week no longer reported is
rebuilt in full.
"""

from __future__ import annotations

import importlib.util
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


def _restamp(data_dir: Path, loaded_through: str | None) -> None:
    """Rewrite every stamp's watermark, keeping its fingerprint (None removes the stamp)."""
    con = connect(data_dir / WAREHOUSE_FILE)
    try:
        for (schema, table), fingerprint in refresh.read_stamps(con).items():
            if fingerprint is None:
                continue
            if loaded_through is None:
                con.execute(f'comment on table "{schema}"."{table}" is null')
            else:
                stamp = json.dumps(
                    {refresh.STAMP_KEY: fingerprint, "loaded_through": loaded_through}
                )
                con.execute(f'comment on table "{schema}"."{table}" is \'{stamp}\'')
    finally:
        con.close()


def test_a_watermark_that_hides_the_late_rows_breaks_the_match(
    built_through_w39: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The comparison can fail: with no lookback and a watermark later than W40's load,
    nothing points back at the late rows, so their weeks stay stale. The late-row test
    warns about exactly these rows."""
    data_dir = _with_w40(built_through_w39, tmp_path)
    _restamp(data_dir, "2099-01-01T00:00:00+00:00")
    _build(data_dir, *NO_LOOKBACK)
    models = _incremental(data_dir)
    assert _floors(data_dir)["mart_org_weekly"] == "2026-W39"
    short = _hashes(data_dir, models)

    _full_refresh(data_dir, monkeypatch)
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


def test_plain_dbt_rebuilds_tables_the_runner_never_stamped(
    built_through_w39: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside the runner (a lab, a manual `dbt run` on a copy) nothing says which rows are
    new, so an unstamped replace_from table rebuilds from the start and stays correct."""
    data_dir = _with_w40(built_through_w39, tmp_path)
    _restamp(data_dir, None)
    _plain_dbt(data_dir, *NO_LOOKBACK)
    models = _incremental(data_dir, "plain-target")
    floors = _floors(data_dir, "plain-target")
    assert all(floors[n] == "" for n in models if n != "fct_activity"), floors
    plain = _hashes(data_dir, models)

    _plain_dbt(data_dir, "--full-refresh")
    assert _hashes(data_dir, models) == plain


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


# ── Master rows, fct_activity's own rule and the stale-book context (re-review) ──

# Loaded after the W40 build's stamp (the W40 ingest ran at 2026-10-05 03:30 UTC).
_LATER = "timestamptz '2026-10-06 03:30:00+00'"


def _late_master_rows(data_dir: Path) -> None:
    """A portfolio master row that moves an existing portfolio to another transit branch,
    and a branch renamed: current-state rows that apply to weeks long before the floor."""
    _execute(
        data_dir,
        f"""
        insert into raw.teradata__prtf
        select * replace (
            (select min("BRNCH_ID") from raw.teradata__brnch where "BRNCH_ID" <> p."BRNCH_ID")
                as "BRNCH_ID",
            {_LATER} as "LAST_UPD_TS",
            {_LATER} as _loaded_at
        )
        from raw.teradata__prtf as p
        where "PRTF_ID" = (
            select min("PRTF_ID") from raw.teradata__prtf_asgn
            where "EFF_DT" = (select min("EFF_DT") from raw.teradata__prtf_asgn)
        );
        insert into raw.teradata__brnch
        select * replace (
            "BRNCH_NM" || ' (renamed)' as "BRNCH_NM",
            {_LATER} as "LAST_UPD_TS",
            {_LATER} as _loaded_at
        )
        from raw.teradata__brnch
        where "BRNCH_ID" = (select min("BRNCH_ID") from raw.teradata__brnch);
        """,
    )


def test_late_master_rows_rebuild_the_weeks_they_change(
    built_through_w39: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _with_w40(built_through_w39, tmp_path)
    _build(data_dir)
    models = _incremental(data_dir)

    _late_master_rows(data_dir)
    _build(data_dir)
    floors = _floors(data_dir)
    assert floors["mart_org_weekly"] == "1900-W01"  # a branch row reaches all of history
    assert floors["mart_org_quarterly"] == ""
    assert floors["int_client_book_weekly"] == "1900-W01"
    incremental = _hashes(data_dir, models)

    _full_refresh(data_dir, monkeypatch)
    assert _hashes(data_dir, models) == incremental


def test_a_late_portfolio_master_reaches_back_to_its_first_assignment(
    built_through_w39: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _with_w40(built_through_w39, tmp_path)
    _build(data_dir)
    models = _incremental(data_dir)
    _late_master_rows(data_dir)
    _execute(data_dir, f"delete from raw.teradata__brnch where _loaded_at = {_LATER}")

    _build(data_dir)
    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    try:
        (first,) = con.execute(
            "select strftime(min(\"EFF_DT\"), '%G-W%V') from raw.teradata__prtf_asgn"
        ).fetchone()  # type: ignore[misc]
    finally:
        con.close()
    assert _floors(data_dir)["int_client_book_weekly"] == first < "2026-W35"
    incremental = _hashes(data_dir, models)

    _full_refresh(data_dir, monkeypatch)
    assert _hashes(data_dir, models) == incremental


def test_fct_activity_warns_on_a_changed_definition_and_keeps_its_history(
    built_through_w39: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fct_activity's owner-approved rule (#275): a changed definition is not restated by
    itself. The stage warns every run until a full refresh; an unstamped table is adopted."""
    data_dir = _with_w40(built_through_w39, tmp_path)
    _build(data_dir)
    old = json.dumps({refresh.STAMP_KEY: "an older definition", "loaded_through": None})
    _execute(data_dir, f"comment on table marts.fct_activity is '{old}'")

    def fct_run() -> str:
        (path,) = (data_dir / stages.DBT_TARGET_DIR / "run").rglob("fct_activity.sql")
        return path.read_text().lower()

    for _ in range(2):  # it keeps warning: the old stamp stays
        result = _build(data_dir)
        assert result.status is StageStatus.WARN
        assert "Definition changed but history kept: fct_activity." in (result.message or "")
        assert "pulse run --full-refresh" in (result.message or "")
        assert "delete from" in fct_run()  # incremental, not rebuilt
    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    try:
        assert refresh.read_stamps(con)[("marts", "fct_activity")] == "an older definition"
    finally:
        con.close()

    _full_refresh(data_dir, monkeypatch)
    after = _build(data_dir)
    assert after.status is StageStatus.SUCCESS, after.message

    _execute(data_dir, "comment on table marts.fct_activity is null")  # built before #304
    adopted = _build(data_dir)
    assert adopted.status is StageStatus.SUCCESS, adopted.message
    assert "delete from" in fct_run()


_spec = importlib.util.spec_from_file_location(
    "stale_book_backdate", ROOT / "tests" / "integration" / "test_stale_book.py"
)
assert _spec and _spec.loader
_stale_book = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stale_book)


def test_the_stale_book_rise_is_the_same_when_rebuilt_from_its_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a year of backdated calls (as in test_stale_book.py) every week has a full
    window and a 13-week rise. The incremental run reads only 13 reported weeks before its
    floor for that rise, and must still equal a full refresh."""
    data_dir = tmp_path / "data"
    _load(data_dir, W39)
    _execute(data_dir, _stale_book._BACKDATE)
    _build(data_dir)
    _load(data_dir, W40)
    _build(data_dir)
    models = _incremental(data_dir)
    floor = _floors(data_dir)["mart_org_weekly"]
    assert floor and floor > "2026-W14"
    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    try:
        rises = con.execute(
            "select count(*) from marts.mart_org_weekly"
            " where level = 'BRANCH' and iso_week_id >= ? and stale_9m_rise_13w <> 0",
            [floor],
        ).fetchone()
    finally:
        con.close()
    assert rises and rises[0] > 10, "no non-zero rise in the rebuilt weeks"
    incremental = _hashes(data_dir, models)

    _full_refresh(data_dir, monkeypatch)
    assert _hashes(data_dir, models) == incremental
