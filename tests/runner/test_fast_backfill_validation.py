"""A backfill loads weeks in order, then finalizes the complete batch."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pulse.generate.cli import activity_dir
from pulse.runner.backfill import backfill_range
from pulse.runner.stage import Stage, StageResult


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 5, 4, tzinfo=UTC)

    def sleep(self, seconds: float) -> None:
        pass


def _pipeline(hooks=None):
    hooks = hooks or {}
    names = (
        "restore_state",
        "generate",
        "ingest",
        "dbt_build",
        "checks",
        "narrate",
        "export",
        "persist_state",
        "release_lock",
    )
    return tuple(
        Stage(
            name,
            name,
            hooks.get(name, lambda ctx: StageResult()),
            (names[i - 1],) if i else (),
            always=name == "release_lock",
        )
        for i, name in enumerate(names)
    )


def test_check_failure_names_week_and_blocks_export_and_persist(tmp_path: Path) -> None:
    from pulse.contracts.enums import StageStatus

    seen = []

    def check(ctx):
        seen.append(ctx.iso_week_id)
        return StageResult(
            StageStatus.FAILED if ctx.iso_week_id == "2026-W38" else StageStatus.SUCCESS
        )

    def forbidden(ctx):
        pytest.fail("must not publish a failed backfill")

    stages = _pipeline({"checks": check, "export": forbidden, "persist_state": forbidden})
    lines = []
    assert (
        backfill_range(
            "2026-W37",
            "2026-W39",
            data_dir=tmp_path,
            stages=stages,
            clock=Clock(),
            echo=lines.append,
        )
        == 1
    )
    assert seen == ["2026-W37", "2026-W38"]
    assert "Stopped at 2026-W38" in lines[-1]


def test_ingest_failure_never_builds_or_persists(tmp_path: Path) -> None:
    from pulse.contracts.enums import StageStatus

    seen = []

    def ingest(ctx):
        seen.append(ctx.iso_week_id)
        return StageResult(
            StageStatus.FAILED if ctx.iso_week_id == "2026-W38" else StageStatus.SUCCESS
        )

    def forbidden(ctx):
        pytest.fail("must not build/persist incomplete ingestion")

    stages = _pipeline({"ingest": ingest, "dbt_build": forbidden, "persist_state": forbidden})
    assert (
        backfill_range("2026-W37", "2026-W39", data_dir=tmp_path, stages=stages, clock=Clock()) == 1
    )
    assert seen == ["2026-W37", "2026-W38"]


def test_budget_resume_checks_every_original_ingest_run(tmp_path: Path) -> None:
    from datetime import timedelta

    class MovingClock(Clock):
        at = datetime(2026, 10, 5, 4, tzinfo=UTC)

        def now(self):
            return self.at

    clock = MovingClock()
    ingested, checked, published, persisted = [], [], [], []

    def ingest(ctx):
        ingested.append((ctx.iso_week_id, ctx.run_id))
        clock.at += timedelta(minutes=10)
        return StageResult()

    def check(ctx):
        checked.append((ctx.iso_week_id, ctx.run_id))
        return StageResult()

    def persist(ctx):
        persisted.append(len(ingested))
        return StageResult()

    def export(ctx):
        published.append(ctx.iso_week_id)
        return StageResult()

    # Historical templates use the same injectable narrative callable in this test.
    import pulse.runner.backfill as module

    original = module._template_narrate
    module._template_narrate = lambda ctx: StageResult()
    try:
        stages = _pipeline(
            {"ingest": ingest, "checks": check, "export": export, "persist_state": persist}
        )
        resume = tmp_path / "next"
        assert (
            backfill_range(
                "2026-W37",
                "2026-W40",
                data_dir=tmp_path,
                stages=stages,
                clock=clock,
                budget=timedelta(minutes=25),
                resume_file=resume,
            )
            == 0
        )
        assert resume.read_text() == "2026-W39\n"
        assert persisted == [2]
        assert not checked and not published
        assert (
            backfill_range(
                "2026-W39",
                "2026-W40",
                data_dir=tmp_path,
                stages=stages,
                clock=clock,
                resume_file=resume,
            )
            == 0
        )
        assert checked == ingested
        assert published == ["2026-W40"]
        assert persisted == [2, 4]
        assert not resume.exists()
    finally:
        module._template_narrate = original


@pytest.mark.integration
@pytest.mark.parametrize(
    "case",
    [
        "fixtures",
        pytest.param("generated", marks=pytest.mark.slow),
        pytest.param("postal-correction", marks=pytest.mark.slow),
    ],
)
def test_fixture_marts_exports_and_weekly_checks_match_legacy(tmp_path, monkeypatch, case):
    import hashlib
    import shutil
    from dataclasses import replace

    import duckdb

    from pulse.contracts.enums import RunType
    from pulse.contracts.exports import EXPORT_TABLE_CONTRACTS
    from pulse.runner.backfill import _template_narrate
    from pulse.runner.command import run_week
    from pulse.runner.dag import WEEKLY_STAGES

    root = Path(__file__).parents[2]
    fixture = root / "fixtures"

    generated = case != "fixtures"
    first = "2026-W33" if generated else "2026-W37"
    from pulse.generate.cli import Sizes, generate_weeks, week_range

    def generate(ctx):
        if generated:
            generate_weeks(
                ctx.data_dir,
                [ctx.iso_week_id],
                seed=42,
                sizes=Sizes(advisors=12, clients=100),
                echo=lambda _: None,
            )
            if case == "postal-correction" and ctx.iso_week_id == "2026-W40":
                import csv
                import sqlite3

                sources = ctx.data_dir / "sources"
                with sqlite3.connect(sources / "teradata/edw.sqlite") as con:
                    con.row_factory = sqlite3.Row
                    row = dict(
                        con.execute("select * from CLNT where CLNT_ID='CLI-00000001'").fetchone()
                    )
                row.update(PSTL_CD="V6B 1A1", PROV_CD="BC", LAST_UPD_TS="2026-10-04 21:00:00")
                with (sources / "teradata/client_20261004_correction.csv").open("w") as f:
                    writer = csv.DictWriter(f, fieldnames=list(row))
                    writer.writeheader()
                    writer.writerow(row)
            return StageResult()
        sources = ctx.data_dir / "sources"
        teradata = sources / "teradata"
        teradata.mkdir(parents=True, exist_ok=True)
        if not (teradata / "edw.sqlite").exists():
            shutil.copy2(fixture / "sources/teradata/edw.sqlite", teradata / "edw.sqlite")
        part = activity_dir(Path("snowflake"), ctx.iso_week_id).name
        cutoff = part.removeprefix("extract_date=").replace("-", "")
        for delta in (fixture / "sources/teradata").glob("client_*.csv"):
            if delta.stem.removeprefix("client_") <= cutoff:
                shutil.copy2(delta, teradata / delta.name)
        source = fixture / "sources/snowflake/activity" / part
        target = sources / "snowflake/activity" / part
        shutil.copytree(source, target, dirs_exist_ok=True)
        shutil.copy2(fixture / "defects.json", ctx.data_dir / "defects.json")
        return StageResult()

    stages = tuple(
        replace(
            s,
            fn=generate
            if s.name == "generate"
            else _template_narrate
            if s.name == "narrate"
            else s.fn,
        )
        for s in WEEKLY_STAGES
    )
    from datetime import timedelta

    import boto3
    from moto import mock_aws

    import pulse.state
    from pulse.state import StateSync
    from pulse.state.store import ObjectStore

    class MovingClock(Clock):
        at = datetime(2026, 10, 5, 4, tzinfo=UTC)

        def now(self):
            return self.at

    original_generate = generate

    def timed_generate(ctx):
        if case == "fixtures":
            ctx.clock.at += timedelta(minutes=10)
        return original_generate(ctx)

    stages = tuple(replace(s, fn=timed_generate) if s.name == "generate" else s for s in stages)
    snapshots = []
    modes = ("legacy", "fast", "resume") if case == "fixtures" else ("legacy", "fast")
    for mode in modes:
        timer = MovingClock() if case == "fixtures" else Clock()
        data = tmp_path / mode
        exports = data / "web"
        monkeypatch.setenv("PULSE_EXPORT_DIR", str(exports))
        monkeypatch.setattr(pulse.state, "STATE", StateSync(lambda: None))
        if mode == "resume":
            with mock_aws():
                client = boto3.client(
                    "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y"
                )
                client.create_bucket(Bucket="pulse-byte-equivalence")
                store = ObjectStore(client, "pulse-byte-equivalence")
                monkeypatch.setattr(pulse.state, "STATE", StateSync(lambda store=store: store))
                resume = tmp_path / "next"
                assert (
                    backfill_range(
                        first,
                        "2026-W40",
                        data_dir=tmp_path / "checkpoint",
                        stages=stages,
                        clock=timer,
                        budget=timedelta(minutes=25),
                        rebuild=True,
                        resume_file=resume,
                    )
                    == 0
                )
                assert resume.read_text() == "2026-W39\n"
                monkeypatch.setattr(pulse.state, "STATE", StateSync(lambda store=store: store))
                assert (
                    backfill_range(
                        "2026-W39", "2026-W40", data_dir=data, stages=stages, clock=timer
                    )
                    == 0
                )
        elif mode == "fast":
            assert backfill_range(first, "2026-W40", data_dir=data, stages=stages, clock=timer) == 0
        else:
            for week in week_range(first, "2026-W40"):
                assert (
                    run_week(
                        week, data_dir=data, run_type=RunType.BACKFILL, stages=stages, clock=timer
                    )
                    == 0
                )
        with duckdb.connect(str(data / "warehouse.duckdb"), read_only=True) as con:
            names = [
                r[0]
                for r in con.execute(
                    "select table_name from information_schema.tables where table_schema='marts'"
                ).fetchall()
            ]
            hashes = {
                name: hashlib.sha256(
                    repr(
                        con.execute(f'SELECT * FROM marts."{name}" ORDER BY ALL').fetchall()
                    ).encode()
                ).hexdigest()
                for name in names
            }
            assert {"fct_activity"} | {
                f"mart_{c.contract_name}" for c in EXPORT_TABLE_CONTRACTS
            } <= hashes.keys()
            checks = con.execute(
                "select run_id, check_id, status from meta.check_result order by all"
            ).fetchall()
            dq033 = [(run, status) for run, check, status in checks if check == "DQ033"]
            expected_weeks = week_range(first, "2026-W40")
            assert len(dq033) == len(expected_weeks)
            assert set(dq033) == {(f"backfill-{week}-1", "PASS") for week in expected_weeks}
            logs = con.execute(
                "select iso_week_id, stage, status from meta.run_log "
                "where stage in ('generate','ingest','checks','narrate') "
                "and run_id not like 'backfill-range-%' order by all"
            ).fetchall()
            expected_stages = {"generate", "ingest", "checks", "narrate"}
            assert len(logs) == len(expected_weeks) * len(expected_stages)
            assert {(week, stage) for week, stage, _ in logs} == {
                (week, stage) for week in expected_weeks for stage in expected_stages
            }
            stable_fact = hashlib.sha256(
                repr(
                    con.execute(
                        "select * exclude(fsa_code, client_sk) from marts.fct_activity order by all"
                    ).fetchall()
                ).encode()
            ).hexdigest()
        parquet = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in exports.glob("*.parquet")
        }
        assert set(parquet) == {f"{c.contract_name}.parquet" for c in EXPORT_TABLE_CONTRACTS}
        snapshots.append((hashes, checks, logs, parquet, stable_fact))
    if case == "postal-correction":
        # Owner-approved #275 exception: full rebuild reapplies current client attributes
        # to old facts. KPI marts, exported data, checks and weekly stage outcomes agree.
        assert snapshots[0][0].pop("fct_activity") != snapshots[1][0].pop("fct_activity")
    assert all(snapshot == snapshots[0] for snapshot in snapshots[1:])


@pytest.mark.integration
def test_fresh_runner_restores_budget_checkpoint_and_weekly_defects(tmp_path, monkeypatch):
    import json
    from dataclasses import replace
    from datetime import timedelta

    import boto3
    from moto import mock_aws

    import pulse.runner.backfill as module
    import pulse.state
    from pulse.contracts.defects import Defect, DefectKind, DefectManifest
    from pulse.contracts.enums import StageStatus
    from pulse.runner.dag import WEEKLY_STAGES
    from pulse.runner.stages import load_defects
    from pulse.state import StateSync
    from pulse.state.store import ObjectStore
    from pulse.warehouse import connect

    class MovingClock(Clock):
        at = datetime(2026, 10, 5, 4, tzinfo=UTC)

        def now(self):
            return self.at

    clock = MovingClock()
    observed = []
    expected = {}
    failing_week = None

    def generate(ctx):
        folder = ctx.data_dir / "defects"
        folder.mkdir(parents=True, exist_ok=True)
        manifest = DefectManifest(
            generated_at=clock.now(),
            seed=42,
            iso_weeks=[ctx.iso_week_id],
            defects=[
                Defect(
                    kind=DefectKind.NULL_ACTIVITY_ID,
                    iso_week_id=ctx.iso_week_id,
                    source="snowflake",
                    table_name="activity",
                    file=f"snowflake/activity/{ctx.iso_week_id}.parquet",
                    row=int(ctx.iso_week_id[-2:]),
                    rule_id="DQ001",
                    detail=f"Injected null activity id for {ctx.iso_week_id}",
                )
            ],
        )
        expected[ctx.iso_week_id] = manifest.model_dump_json()
        (folder / f"{ctx.iso_week_id}.json").write_text(expected[ctx.iso_week_id])
        return StageResult()

    def ingest(ctx):
        clock.at += timedelta(minutes=10)
        return StageResult(
            StageStatus.FAILED if ctx.iso_week_id == failing_week else StageStatus.SUCCESS
        )

    def check(ctx):
        manifest = load_defects(ctx.data_dir, ctx.iso_week_id, clock.now())
        observed.append((ctx.iso_week_id, manifest.model_dump_json()))
        return StageResult()

    monkeypatch.setattr(module, "_template_narrate", lambda ctx: StageResult())
    stages = tuple(
        s
        if s.name in {"restore_state", "persist_state", "release_lock"}
        else replace(
            s,
            fn=generate
            if s.name == "generate"
            else ingest
            if s.name == "ingest"
            else check
            if s.name == "checks"
            else lambda ctx: StageResult(),
        )
        for s in WEEKLY_STAGES
    )
    with mock_aws():
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y"
        )
        client.create_bucket(Bucket="pulse-checkpoint")
        store = ObjectStore(client, "pulse-checkpoint")

        def fresh():
            monkeypatch.setattr(
                pulse.state,
                "STATE",
                StateSync(lambda: store, rebuild=lambda ctx, weeks: StageResult()),
            )

        fresh()
        resume = tmp_path / "next"
        assert (
            backfill_range(
                "2026-W37",
                "2026-W40",
                data_dir=tmp_path / "first",
                stages=stages,
                clock=clock,
                rebuild=True,
                budget=timedelta(minutes=25),
                resume_file=resume,
            )
            == 0
        )
        assert resume.read_text() == "2026-W39\n"
        progress = json.loads(store.get("sources/backfill-progress.json")[0])
        assert [e["week"] for e in progress["pending"]] == ["2026-W37", "2026-W38"]
        # Sources upload before the warehouse. A failed upload must not let newer
        # source-side progress claim ingest runs that the restored warehouse lacks.
        corrupt = json.loads(json.dumps(progress))
        corrupt["pending"][0]["run_id"] = "missing-ingest-run"
        store.put("sources/backfill-progress.json", json.dumps(corrupt).encode())
        fresh()
        assert (
            backfill_range(
                "2026-W39", "2026-W40", data_dir=tmp_path / "corrupt", stages=stages, clock=clock
            )
            == 1
        )
        assert not observed
        store.put("sources/backfill-progress.json", json.dumps(progress).encode())
        fresh()
        assert (
            backfill_range(
                "2026-W39", "2026-W40", data_dir=tmp_path / "fresh", stages=stages, clock=clock
            )
            == 0
        )
        assert observed == [
            (w, expected[w]) for w in ("2026-W37", "2026-W38", "2026-W39", "2026-W40")
        ]
        with connect(tmp_path / "fresh" / "warehouse.duckdb", read_only=True) as con:
            rows = con.execute(
                "select iso_week_id, status from meta.run_log where stage='checks' "
                "and run_id not like 'backfill-range-%' order by all"
            ).fetchall()
        assert rows == [
            (w, StageStatus.SUCCESS.value) for w in ("2026-W37", "2026-W38", "2026-W39", "2026-W40")
        ]
        assert not store.exists("lock.json")
        # Failure after a periodic checkpoint must leave remote data at that checkpoint.
        monkeypatch.setattr(module, "CHECKPOINT_WEEKS", 2)
        failing_week = "2026-W44"
        fresh()
        assert (
            backfill_range(
                "2026-W41",
                "2026-W44",
                data_dir=tmp_path / "failed",
                stages=stages,
                clock=clock,
                budget=timedelta(minutes=100),
            )
            == 1
        )
        progress = json.loads(store.get("sources/backfill-progress.json")[0])
        assert [e["week"] for e in progress["pending"]] == ["2026-W41", "2026-W42"]
        remote = tmp_path / "checkpoint.duckdb"
        store.download("warehouse.duckdb", remote)
        with connect(remote, read_only=True) as con:
            assert con.execute(
                "select max(iso_week_id) from meta.run_log where stage='ingest' "
                "and run_id not like 'backfill-range-%'"
            ).fetchone() == ("2026-W42",)
        assert not store.exists("lock.json")


def test_lock_contention_is_not_a_completed_backfill(tmp_path):
    from pulse.contracts.enums import StageStatus

    stages = _pipeline({"restore_state": lambda ctx: StageResult(StageStatus.SKIPPED, halt=True)})
    assert (
        backfill_range("2026-W37", "2026-W40", data_dir=tmp_path, stages=stages, clock=Clock()) == 1
    )
