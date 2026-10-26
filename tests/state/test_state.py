from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

import pulse.state
from pulse.contracts.enums import RunType, StageStatus
from pulse.ingest import meta
from pulse.runner import WEEKLY_STAGES, RetryableError, Stage, StageContext, StageResult
from pulse.runner.command import run_week
from pulse.state import StateSync, lock, weeks_between
from pulse.state.store import ObjectStore, R2Config
from pulse.warehouse import WAREHOUSE_FILE, connect, init_warehouse

BUCKET = "pulse-state"
WEEK = "2026-W40"
T0 = datetime(2026, 10, 5, 11, 0, tzinfo=UTC)


class Clock:
    def __init__(self, start: datetime = T0) -> None:
        self.t = start

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def store() -> Iterator[ObjectStore]:
    with mock_aws():
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y"
        )
        client.create_bucket(Bucket=BUCKET)
        yield ObjectStore(client, BUCKET)


_TOKENS = count(1)


def sync_for(store: ObjectStore, **kw: object) -> StateSync:
    """One StateSync per simulated process; tokens are unique like real uuid4 tokens."""
    return StateSync(lambda: store, new_token=lambda: f"token-{next(_TOKENS)}", **kw)  # type: ignore[arg-type]


def ctx(
    data_dir: Path, run_id: str = f"weekly-{WEEK}-1", clock: Clock | None = None
) -> StageContext:
    return StageContext(run_id, RunType.WEEKLY, WEEK, data_dir, clock or Clock())


def seed_remote(store: ObjectStore, tmp_path: Path) -> None:
    """R2 already holds a warehouse with one run and two source files."""
    src = tmp_path / "seed"
    src.mkdir()
    con = connect(src / WAREHOUSE_FILE)
    init_warehouse(con)
    con.close()
    store.upload(src / WAREHOUSE_FILE, WAREHOUSE_FILE)
    store.put("sources/snowflake/activity/a.csv", b"A")
    store.put("sources/teradata/client_20261001.csv", b"C")


# ── Round trip ──────────────────────────────────────────────────────────────


def work_stage(ctx: StageContext) -> StageResult:
    """Stands in for generate/ingest: adds a source file the next run must see."""
    path = ctx.data_dir / "sources" / "snowflake" / "activity" / f"{ctx.run_id}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ctx.run_id)
    return StageResult()


def state_stages() -> list[Stage]:
    by_name = {s.name: s for s in WEEKLY_STAGES}
    return [
        by_name["restore_state"],
        Stage("work", "Work", work_stage, ("restore_state",)),
        Stage("persist_state", "Persist state", by_name["persist_state"].fn, ("work",)),
        Stage(
            "release_lock",
            "Release lock",
            by_name["release_lock"].fn,
            ("persist_state",),
            always=True,
        ),
    ]


def test_restore_run_persist_round_trip(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_remote(store, tmp_path)
    monkeypatch.setattr(pulse.state, "STATE", sync_for(store))
    clock = Clock()

    # Two ephemeral runners: each starts from an empty data dir.
    first, second = tmp_path / "runner1", tmp_path / "runner2"
    for data_dir in (first, second):
        code = run_week(
            WEEK,
            data_dir=data_dir,
            run_type=RunType.WEEKLY,
            stages=state_stages(),
            clock=clock,
            echo=lambda _: None,
        )
        assert code == 0
        clock.sleep(3600)

    # The second runner restored the first runner's sources and warehouse.
    activity = second / "sources" / "snowflake" / "activity"
    assert sorted(p.name for p in activity.iterdir()) == [
        "a.csv",
        f"weekly-{WEEK}-1.csv",
        f"weekly-{WEEK}-2.csv",
    ]
    assert (second / "sources" / "teradata" / "client_20261001.csv").read_bytes() == b"C"
    assert f"sources/snowflake/activity/weekly-{WEEK}-2.csv" in store.etags("sources/")

    # run_ids stay unique across fresh runners, and both runs' log rows survive.
    con = connect(second / WAREHOUSE_FILE, read_only=True)
    runs = {r.run_id for r in meta.get_run_log(con)}
    con.close()
    assert runs == {f"weekly-{WEEK}-1", f"weekly-{WEEK}-2"}
    assert pulse.state.STATE.known_run_ids() == runs
    assert lock.holder(store) is None  # released


def test_persist_skips_unchanged_sources(store: ObjectStore, tmp_path: Path) -> None:
    seed_remote(store, tmp_path)
    sync = sync_for(store)
    c = ctx(tmp_path / "run")
    assert sync.restore(c).status is StageStatus.SUCCESS
    result = sync.persist(c)
    assert result.status is StageStatus.SUCCESS
    assert result.rows_out == 0  # both restored files match their remote MD5
    (c.data_dir / "sources" / "teradata" / "client_20261001.csv").write_bytes(b"changed")
    assert sync.persist(c).rows_out == 1
    assert sync.release(c).message == "Released run lock."


def test_narratives_and_their_cache_survive_ephemeral_runners(
    store: ObjectStore, tmp_path: Path
) -> None:
    # The weekly run narrates only its own week, and a cold rebuild narrates none, so the
    # published history and the model cache exist only if R2 carries them between runners.
    seed_remote(store, tmp_path)
    first = sync_for(store)
    c1 = ctx(tmp_path / "runner1")
    assert first.restore(c1).status is StageStatus.SUCCESS
    narratives = c1.data_dir / "narratives"
    (narratives / "cache").mkdir(parents=True)
    (narratives / "2026-W39.json").write_text('{"week": 39}')
    (narratives / "cache" / "abc123.json").write_text('{"text": "cached"}')
    persisted = first.persist(c1)
    assert (persisted.message or "").endswith("plus 2 narrative files.")
    first.release(c1)
    remote = set(store.etags("narratives/"))
    assert {"narratives/2026-W39.json", "narratives/cache/abc123.json"} <= remote

    second = sync_for(store)
    c2 = ctx(tmp_path / "runner2", run_id=f"weekly-{WEEK}-2")
    restored = second.restore(c2)
    assert "2 narrative files" in (restored.message or "")
    cached = c2.data_dir / "narratives" / "cache" / "abc123.json"
    assert cached.read_text() == '{"text": "cached"}'
    # Unchanged files are not uploaded again.
    assert (second.persist(c2).message or "").endswith("plus 0 narrative files.")
    second.release(c2)


def test_a_failed_narrative_upload_still_keeps_the_warehouse(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_remote(store, tmp_path)
    sync = sync_for(store)
    c = ctx(tmp_path / "run")
    assert sync.restore(c).status is StageStatus.SUCCESS
    (c.data_dir / "narratives").mkdir()
    (c.data_dir / "narratives" / "2026-W40.json").write_text("{}")
    upload = store.upload_if_changed

    def flaky(path: Path, key: str, etag: str | None) -> bool:
        if key.startswith("narratives/"):
            raise RetryableError("R2 timed out")
        return upload(path, key, etag)

    uploaded: list[str] = []
    whole = store.upload

    def recording(path: Path, key: str) -> None:
        uploaded.append(key)
        whole(path, key)

    monkeypatch.setattr(store, "upload_if_changed", flaky)
    monkeypatch.setattr(store, "upload", recording)
    result = sync.persist(c)
    assert result.status is StageStatus.WARN
    assert "narratives were not persisted (RetryableError)" in (result.message or "")
    assert uploaded == [WAREHOUSE_FILE]  # the checked warehouse still went up
    assert sync.release(c).status is StageStatus.SUCCESS


def test_a_failed_narrative_prune_still_keeps_the_warehouse(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rebuild's narrative prune is best effort, like the narrative upload."""
    seed_remote(store, tmp_path)
    store.put("narratives/2026-W39.json", b"N")
    sync = sync_for(store)
    c = ctx(tmp_path / "rebuild")
    assert sync.restore(c, skip_remote=True).status is StageStatus.SUCCESS
    con = connect(c.data_dir / WAREHOUSE_FILE)
    init_warehouse(con)
    con.close()
    delete = store.delete

    def flaky(key: str) -> None:
        if key.startswith("narratives/"):
            raise RetryableError("R2 timed out")
        delete(key)

    monkeypatch.setattr(store, "delete", flaky)
    result = sync.persist(c)
    assert result.status is StageStatus.WARN
    assert "narratives were not persisted (RetryableError)" in (result.message or "")
    assert store.exists(WAREHOUSE_FILE)  # the checked warehouse still went up
    assert sync.release(c).status is StageStatus.SUCCESS


# ── Lock ────────────────────────────────────────────────────────────────────


def test_second_concurrent_run_exits_skipped(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_remote(store, tmp_path)
    clock = Clock()
    other_process = sync_for(store)
    first = ctx(tmp_path / "a", "weekly-2026-W40-1", clock)
    assert other_process.restore(first).status is StageStatus.SUCCESS  # run 1 holds the lock
    monkeypatch.setattr(pulse.state, "STATE", sync_for(store))

    lines: list[str] = []
    code = run_week(
        WEEK,
        data_dir=tmp_path / "b",
        run_type=RunType.WEEKLY,
        stages=state_stages(),
        clock=clock,
        echo=lines.append,
    )
    assert code == 0
    assert lines[-1].endswith(": SKIPPED")
    assert any("Run lock held by weekly-2026-W40-1 until 2026-10-05 13:00 UTC." in x for x in lines)
    assert any("Run stopped at restore_state" in x for x in lines)
    # Run 2 touched nothing: no work, no upload, and run 1 still holds the lock.
    assert not (tmp_path / "b" / "sources").exists()
    holder = lock.holder(store)
    assert holder is not None and holder.run_id == "weekly-2026-W40-1"


def test_expired_lock_is_taken_over(store: ObjectStore, tmp_path: Path) -> None:
    seed_remote(store, tmp_path)
    sync = sync_for(store)
    clock = Clock()
    stale = ctx(tmp_path / "a", "weekly-2026-W40-1", clock)
    assert sync.restore(stale).status is StageStatus.SUCCESS

    clock.t += lock.LOCK_TTL + timedelta(seconds=1)
    fresh = ctx(tmp_path / "b", "weekly-2026-W40-2", clock)
    result = sync.restore(fresh)
    assert result.status is StageStatus.SUCCESS
    assert "Took over expired lock from weekly-2026-W40-1." in (result.message or "")

    # The stale run wakes up: it must not overwrite state or delete the new holder's lock.
    persisted = sync.persist(stale)
    assert persisted.status is StageStatus.FAILED
    assert "now held by weekly-2026-W40-2" in (persisted.message or "")
    assert sync.release(stale).status is StageStatus.WARN
    holder = lock.holder(store)
    assert holder is not None and holder.run_id == "weekly-2026-W40-2"


def test_retried_restore_keeps_its_own_lock(store: ObjectStore, tmp_path: Path) -> None:
    seed_remote(store, tmp_path)
    sync = sync_for(store)
    c = ctx(tmp_path / "a")
    assert sync.restore(c).status is StageStatus.SUCCESS
    assert sync.restore(c).status is StageStatus.SUCCESS  # same token: not "held by itself"


def test_rebuild_restore_takes_lock_without_restoring_old_state(
    store: ObjectStore, tmp_path: Path
) -> None:
    seed_remote(store, tmp_path)
    sync = sync_for(store)
    c = ctx(tmp_path / "rebuild")
    result = sync.restore(c, skip_remote=True)
    assert result.status is StageStatus.SUCCESS
    assert "empty local state" in (result.message or "")
    assert not (c.data_dir / WAREHOUSE_FILE).exists()
    assert not (c.data_dir / "sources").exists()
    assert not store.exists(WAREHOUSE_FILE)  # a stopped rebuild makes the next run rebuild cold
    assert lock.holder(store) is not None
    assert sync.release(c).status is StageStatus.SUCCESS


def test_rebuild_persist_removes_stale_sources(store: ObjectStore, tmp_path: Path) -> None:
    """Week 2 of a rebuild restores R2's sources, so older files must be gone by then."""
    seed_remote(store, tmp_path)
    store.put("narratives/2026-W39.json", b"N")
    store.put("narratives/cache/abc.json", b"C")
    sync = sync_for(store)
    c = ctx(tmp_path / "rebuild")
    assert sync.restore(c, skip_remote=True).status is StageStatus.SUCCESS
    con = connect(c.data_dir / WAREHOUSE_FILE)
    init_warehouse(con)
    con.close()
    fresh = c.data_dir / "sources" / "teradata" / "client_20261001.csv"
    fresh.parent.mkdir(parents=True)
    fresh.write_bytes(b"new")
    result = sync.persist(c)
    assert result.status is StageStatus.SUCCESS
    assert "removed 1 stale sources" in (result.message or "")
    assert "narrative files, removed 1 stale ones" in (result.message or "")
    assert set(store.etags("sources/")) == {"sources/teradata/client_20261001.csv"}
    assert store.get("sources/teradata/client_20261001.csv")[0] == b"new"  # type: ignore[index]
    # Week 2 would restore an older run's narrative and export would re-validate it against
    # today's contract (a retired KPI code fails the whole export); the model cache stays.
    assert not store.exists("narratives/2026-W39.json")
    assert store.exists("narratives/cache/abc.json")
    assert sync.release(c).status is StageStatus.SUCCESS


def test_ordinary_persist_never_removes_sources(store: ObjectStore, tmp_path: Path) -> None:
    seed_remote(store, tmp_path)
    store.put("narratives/2026-W39.json", b"N")
    sync = sync_for(store)
    c = ctx(tmp_path / "run")
    assert sync.restore(c).status is StageStatus.SUCCESS
    (c.data_dir / "sources" / "snowflake" / "activity" / "a.csv").unlink()
    (c.data_dir / "narratives" / "2026-W39.json").unlink()
    result = sync.persist(c)
    assert "stale" not in (result.message or "")
    assert store.exists("sources/snowflake/activity/a.csv")
    assert store.exists("narratives/2026-W39.json")
    assert sync.release(c).status is StageStatus.SUCCESS


def test_failed_run_still_releases_the_lock(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_remote(store, tmp_path)
    monkeypatch.setattr(pulse.state, "STATE", sync_for(store))

    def boom(ctx: StageContext) -> StageResult:
        return StageResult(StageStatus.FAILED, message="dbt build failed")

    stages = [replace_fn(s, boom) if s.name == "work" else s for s in state_stages()]
    code = run_week(
        WEEK,
        data_dir=tmp_path / "a",
        run_type=RunType.WEEKLY,
        stages=stages,
        clock=Clock(),
        echo=lambda _: None,
    )
    assert code == 1
    assert lock.holder(store) is None
    assert not store.exists("sources/snowflake/activity/weekly-2026-W40-1.csv")


def replace_fn(stage: Stage, fn: object) -> Stage:
    from dataclasses import replace

    return replace(stage, fn=fn)  # type: ignore[arg-type]


# ── Cold rebuild ────────────────────────────────────────────────────────────


def test_clear_local_is_public_and_preserves_unrelated_files(tmp_path: Path) -> None:
    from pulse.state.sync import clear_local

    (tmp_path / WAREHOUSE_FILE).write_bytes(b"stale")
    (tmp_path / "defects.json").write_text("stale")
    (tmp_path / "keep.txt").write_text("keep")

    clear_local(tmp_path)

    assert not (tmp_path / WAREHOUSE_FILE).exists()
    assert not (tmp_path / "defects.json").exists()
    assert (tmp_path / "keep.txt").read_text() == "keep"


def test_weeks_between_crosses_iso_year() -> None:
    assert weeks_between("2026-W52", "2027-W02") == ["2026-W52", "2026-W53", "2027-W01"]
    assert weeks_between("2026-W40", "2026-W40") == []


def test_missing_warehouse_triggers_cold_rebuild(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty bucket: rebuild W37..W39 through the real backfill path, then run W40."""
    monkeypatch.setattr(pulse.state, "STATE", sync_for(store, start_week="2026-W37"))
    # Sources whose warehouse upload never happened, e.g. from a rebuild that stopped.
    store.put("sources/snowflake/activity/old_generation.csv", b"O")
    data_dir = tmp_path / "runner"
    stale = data_dir / "sources" / "stale.csv"
    stale.parent.mkdir(parents=True)
    stale.write_text("left over from an earlier local run")

    lines: list[str] = []
    code = run_week(
        WEEK, data_dir=data_dir, run_type=RunType.WEEKLY, clock=Clock(), echo=lines.append
    )
    assert code == 0
    restore = next(x for x in lines if x.strip().startswith("restore_state"))
    assert "Cold start: no state in R2. Rebuilt 3 weeks (2026-W37..2026-W39)." in restore

    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    rows = meta.get_run_log(con)
    con.close()
    backfills = sorted({r.run_id for r in rows if r.run_type is RunType.BACKFILL})
    assert backfills == ["backfill-2026-W37-1", "backfill-2026-W38-1", "backfill-2026-W39-1"]
    assert not {r.stage for r in rows if r.run_type is RunType.BACKFILL} & pulse.state.STATE_STAGES
    assert not {r.stage for r in rows if r.run_type is RunType.BACKFILL} & {"narrate"}
    assert not stale.exists()  # cold start begins from nothing
    assert store.exists(WAREHOUSE_FILE)  # persisted, so the next run restores instead
    assert not store.exists("sources/snowflake/activity/old_generation.csv")
    assert lock.holder(store) is None


def test_failed_cold_rebuild_fails_restore(store: ObjectStore, tmp_path: Path) -> None:
    def rebuild(ctx: StageContext, weeks: Sequence[str]) -> StageResult:
        return StageResult(StageStatus.FAILED, message=f"Cold rebuild failed at {weeks[0]}.")

    sync = sync_for(store, rebuild=rebuild, start_week="2026-W38")
    result = sync.restore(ctx(tmp_path))
    assert result.status is StageStatus.FAILED
    assert result.message == "Cold start: Cold rebuild failed at 2026-W38."


def test_cold_start_at_the_first_week_rebuilds_nothing(store: ObjectStore, tmp_path: Path) -> None:
    sync = sync_for(store, start_week=WEEK)
    result = sync.restore(ctx(tmp_path))
    assert (result.status, result.message) == (StageStatus.SUCCESS, "Cold start: no state in R2.")


# ── No credentials ──────────────────────────────────────────────────────────


def test_absent_credentials_skip_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert R2Config.from_env({}) is None
    assert R2Config.from_env({"R2_BUCKET": "b", "R2_ENDPOINT_URL": "https://x"}) is None
    sync = StateSync()  # reads the (cleared) environment
    c = ctx(tmp_path)
    with caplog.at_level(logging.WARNING, logger="pulse.state.sync"):
        restored = sync.restore(c)
    assert restored.status is StageStatus.SKIPPED
    assert "R2 credentials absent" in (restored.message or "")
    assert "R2 credentials absent" in caplog.text
    assert sync.persist(c).status is StageStatus.SKIPPED
    assert sync.release(c).status is StageStatus.SKIPPED


def test_local_run_without_credentials_succeeds(tmp_path: Path) -> None:
    code = run_week(
        WEEK, data_dir=tmp_path, run_type=RunType.MANUAL, clock=Clock(), echo=lambda _: None
    )
    assert code == 0


# ── Transient errors ────────────────────────────────────────────────────────


class Unavailable:
    def get_object(self, **_: object) -> None:
        raise ClientError(
            {"Error": {"Code": "ServiceUnavailable"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
            "GetObject",
        )


def test_server_errors_are_retryable() -> None:
    store = ObjectStore(Unavailable(), BUCKET)  # type: ignore[arg-type]
    with pytest.raises(RetryableError):
        store.get("lock.json")


# ── Incremental restore (#206) ──────────────────────────────────────────────


def test_restore_downloads_only_what_differs(store: ObjectStore, tmp_path: Path) -> None:
    seed_remote(store, tmp_path)
    data_dir = tmp_path / "runner"
    sync = sync_for(store)

    first = sync.restore(ctx(data_dir, "backfill-a"))
    assert "restored warehouse.duckdb, 2 source files and 0 narrative files (2 downloaded)" in (
        first.message or ""
    )
    assert sync.persist(ctx(data_dir, "backfill-a")).status is StageStatus.SUCCESS
    sync.release(ctx(data_dir, "backfill-a"))

    # The next week on the same runner: nothing changed, so nothing is fetched.
    second = sync.restore(ctx(data_dir, "backfill-b"))
    assert "kept the local warehouse.duckdb" in (second.message or "")
    assert "(0 downloaded)" in (second.message or "")

    # A source edited remotely, and a local warehouse touched after persist, are fetched again.
    sync.release(ctx(data_dir, "backfill-b"))
    store.put("sources/teradata/client_20261001.csv", b"C2")
    con = connect(data_dir / WAREHOUSE_FILE)
    con.execute("CREATE TABLE meta.after_persist (x INTEGER)")
    con.close()
    third = sync.restore(ctx(data_dir, "backfill-c"))
    assert "restored warehouse.duckdb" in (third.message or "")
    assert "(1 downloaded)" in (third.message or "")
    assert (data_dir / "sources/teradata/client_20261001.csv").read_bytes() == b"C2"
    con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
    tables = {
        r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    con.close()
    assert "after_persist" not in tables


def test_a_corrupt_marker_falls_back_to_downloading(store: ObjectStore, tmp_path: Path) -> None:
    seed_remote(store, tmp_path)
    data_dir = tmp_path / "runner"
    sync = sync_for(store)
    sync.restore(ctx(data_dir, "backfill-a"))
    sync.persist(ctx(data_dir, "backfill-a"))
    sync.release(ctx(data_dir, "backfill-a"))
    for broken in ('{"etag": "x", "si', "[1, 2]"):
        (data_dir / "warehouse.r2.json").write_text(broken)
        result = sync.restore(ctx(data_dir, f"backfill-{len(broken)}"))
        assert result.status is StageStatus.SUCCESS
        assert "restored warehouse.duckdb" in (result.message or "")
        sync.release(ctx(data_dir, f"backfill-{len(broken)}"))


def test_backfill_cold_restore_leaves_requested_range_to_the_caller(store, tmp_path):
    def forbidden(ctx, weeks):
        pytest.fail("backfill restore must not run legacy weekly dbt builds")

    sync = sync_for(store, rebuild=forbidden)
    result = sync.restore(ctx(tmp_path), rebuild_missing=False)
    assert result.status is StageStatus.SUCCESS
    assert "requested range" in result.message
    assert sync.release(ctx(tmp_path)).status is StageStatus.SUCCESS


# ── Parallel restore (#354) ────────────────────────────────────────────────


def test_parallel_restore_matches_sequential_and_preserves_remote(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Barrier, Lock

    from boto3.s3.transfer import TransferConfig

    seed_remote(store, tmp_path)
    for i in range(32):
        store.put(f"sources/history/{i}.csv", bytes(range(256)) + str(i).encode())
        store.put(f"narratives/cache/{i}.json", f'{{"cached": {i}}}'.encode())
    keys = {**store.etags("sources/"), **store.etags("narratives/")}
    before = {key: store.get(key) for key in keys}
    sequential = tmp_path / "sequential"
    for key in [WAREHOUSE_FILE, *sorted(keys)]:
        dest = sequential / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        store.client.download_file(
            BUCKET, store._key(key), str(dest), Config=TransferConfig(use_threads=False)
        )

    # Deterministic overlap proof: the first 16 calls must all be in flight together.
    barrier, guard = Barrier(16, timeout=5), Lock()
    active = peak = calls = 0
    download = store.download_if_changed

    def overlapping(key: str, path: Path, etag: str) -> bool:
        nonlocal active, peak, calls
        with guard:
            active += 1
            calls += 1
            first_wave = calls <= 16
            peak = max(peak, active)
        try:
            if first_wave:
                barrier.wait()
            return download(key, path, etag)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(store, "download_if_changed", overlapping)
    sync = sync_for(store)
    c = ctx(tmp_path / "parallel")
    restored = sync.restore(c)
    assert restored.status is StageStatus.SUCCESS
    assert peak == 16
    assert calls == len(keys)
    assert f"({len(keys)} downloaded)" in (restored.message or "")
    for key in [WAREHOUSE_FILE, *keys]:
        assert (c.data_dir / key).read_bytes() == (sequential / key).read_bytes(), key
    assert sync.persist(c).status is StageStatus.SUCCESS
    assert {key: store.get(key) for key in keys} == before
    assert set(store.etags("sources/")) | set(store.etags("narratives/")) == set(keys)
    sync.release(c)


def test_warehouse_download_uses_ranges(store: ObjectStore, tmp_path: Path) -> None:
    from threading import Barrier

    content = bytes(range(256)) * (129 * 1024)  # 32.25 MiB: at least three 16 MiB ranges
    store.put(WAREHOUSE_FILE, content)
    ranges: list[str] = []
    barrier = Barrier(3, timeout=5)

    def ranged(params: dict[str, object], **_: object) -> None:
        ranges.append(str(params.get("Range")))
        barrier.wait()

    store.client.meta.events.register("before-parameter-build.s3.GetObject", ranged)
    dest = tmp_path / WAREHOUSE_FILE
    store.download(WAREHOUSE_FILE, dest, parallel=True)
    assert len(ranges) == 3
    assert all(value.startswith("bytes=") for value in ranges)
    assert dest.read_bytes() == content
    assert sorted(p.name for p in tmp_path.iterdir()) == [WAREHOUSE_FILE]


@pytest.mark.parametrize("key", ["sources/broken.csv", "narratives/broken.json", WAREHOUSE_FILE])
@pytest.mark.parametrize("permanent", [False, True])
def test_stream_retry_and_failed_restore_never_persists(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, permanent: bool
) -> None:
    from io import BytesIO
    from unittest.mock import Mock

    from botocore.exceptions import ReadTimeoutError
    from botocore.response import StreamingBody

    seed_remote(store, tmp_path)
    if key != WAREHOUSE_FILE:
        store.put(key, b"synthetic data" * 1024)
    remote = {k: store.get(k) for k in store.etags("")}
    attempts = 0
    get_object = store.client.get_object

    class Interrupted(BytesIO):
        def read(self, size: int = -1) -> bytes:
            if self.tell():
                raise ReadTimeoutError(endpoint_url="https://synthetic.invalid")
            return super().read(min(size, 1024))

    def flaky(**kwargs):
        nonlocal attempts
        response = get_object(**kwargs)
        if kwargs["Key"] == store._key(key):
            attempts += 1
            if permanent or attempts == 1:
                body = response["Body"]
                content = body.read()
                body.close()
                response["Body"] = StreamingBody(Interrupted(content), len(content))
        return response

    monkeypatch.setattr(store.client, "get_object", flaky)
    sync = sync_for(store)
    persist = Mock(wraps=sync.persist)
    monkeypatch.setattr(sync, "persist", persist)
    monkeypatch.setattr(pulse.state, "STATE", sync)
    data_dir = tmp_path / "run"
    out: list[str] = []
    code = run_week(
        WEEK,
        data_dir=data_dir,
        run_type=RunType.WEEKLY,
        stages=state_stages(),
        clock=Clock(),
        echo=out.append,
    )
    assert code == int(permanent), out
    assert attempts == (15 if permanent else 2)  # five stream attempts × three stage attempts
    assert not list(data_dir.rglob("*.partial*"))
    if permanent:
        # WarehouseSink creates a local warehouse to record the failed run itself.
        if key != WAREHOUSE_FILE:
            assert not (data_dir / key).exists()
        assert any(key in line and "FAILED" in line for line in out)
        persist.assert_not_called()
    else:
        persist.assert_called_once()
    assert lock.holder(store) is None
    # The failed restore may only have acquired/released its lock; remote state is untouched.
    if permanent:
        monkeypatch.setattr(store.client, "get_object", get_object)
        assert {k: store.get(k) for k in store.etags("")} == remote


def test_download_rename_failure_cleans_partial_and_keeps_target(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.put("sources/a.csv", b"new")
    dest = tmp_path / "a.csv"
    dest.write_bytes(b"old")
    replace = Path.replace

    def fail_partial(path: Path, target: Path) -> Path:
        if path == dest.with_name("a.csv.partial"):
            raise OSError("simulated rename failure")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_partial)
    with pytest.raises(RuntimeError, match=r"sources/a\.csv.*simulated rename failure"):
        store.download("sources/a.csv", dest)
    assert dest.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.csv"]


def test_missing_download_names_key_and_keeps_existing_file(
    store: ObjectStore, tmp_path: Path
) -> None:
    dest = tmp_path / "a.csv"
    dest.write_bytes(b"existing")
    with pytest.raises(RuntimeError, match=r"sources/missing\.csv"):
        store.download("sources/missing.csv", dest)
    assert dest.read_bytes() == b"existing"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.csv"]


def test_failed_warehouse_range_is_atomic(
    store: ObjectStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from botocore.exceptions import ReadTimeoutError

    store.put(WAREHOUSE_FILE, bytes(range(256)) * (129 * 1024))
    dest = tmp_path / WAREHOUSE_FILE
    dest.write_bytes(b"existing warehouse")
    get_object = store.client.get_object
    failures = 0

    def flaky(**kwargs):
        nonlocal failures
        if str(kwargs.get("Range", "")).startswith("bytes=16777216-"):
            failures += 1
            raise ReadTimeoutError(endpoint_url="https://synthetic.invalid")
        return get_object(**kwargs)

    monkeypatch.setattr(store.client, "get_object", flaky)
    with pytest.raises(RetryableError, match=WAREHOUSE_FILE):
        store.download(WAREHOUSE_FILE, dest, parallel=True)
    assert failures == 5
    assert dest.read_bytes() == b"existing warehouse"
    assert sorted(p.name for p in tmp_path.iterdir()) == [WAREHOUSE_FILE]
