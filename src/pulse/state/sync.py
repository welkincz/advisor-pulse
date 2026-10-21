"""The restore_state, persist_state and release_lock stages.

R2 layout under ``state/``: ``warehouse.duckdb``, ``sources/<file>`` mirroring
``$PULSE_DATA_DIR/sources``, ``narratives/<file>`` mirroring the published weekly narratives and
their model-response cache (so history accrues and a rerun of a week costs no model calls), and
``lock.json``. Persist uploads sources before the warehouse:
if it stops halfway, R2 holds sources the warehouse has not loaded yet, which the next ingest
picks up. The reverse (a warehouse that saw files R2 lacks) cannot happen.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from pulse.contracts.enums import RunType, StageStatus
from pulse.generate.advisors import DEFAULT_START
from pulse.runner.stage import RetryableError, StageContext, StageResult
from pulse.state import lock
from pulse.state.store import ObjectStore
from pulse.warehouse import WAREHOUSE_FILE

log = logging.getLogger(__name__)

SOURCES_DIR = "sources"
NARRATIVES_DIR = "narratives"
# Every run_id in the persisted warehouse. A fresh runner starts with an empty local
# warehouse, so ``pulse run`` reads this to number its run (weekly-2026-W40-2, not -1 again).
RUNS_KEY = "runs.json"
STATE_STAGES = frozenset({"restore_state", "persist_state", "release_lock"})

# Rebuild every week in order, oldest first, into ctx.data_dir. Returns the stage outcome.
Rebuild = Callable[[StageContext, Sequence[str]], StageResult]
StoreFactory = Callable[[], ObjectStore | None]


def _week_id(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


START_WEEK = _week_id(DEFAULT_START)


def weeks_between(first: str, stop: str) -> list[str]:
    """ISO weeks from ``first`` up to but excluding ``stop``."""
    day = date.fromisoformat(f"{first}-1")
    end = date.fromisoformat(f"{stop}-1")
    weeks: list[str] = []
    while day < end:
        weeks.append(_week_id(day))
        day += timedelta(weeks=1)
    return weeks


def backfill_rebuild(ctx: StageContext, weeks: Sequence[str]) -> StageResult:
    """Run the weekly stages, minus the state stages, for each week as a BACKFILL run."""
    # Imported on call: pulse.runner.dag imports this module's stages lazily the same way.
    from pulse.ingest import meta
    from pulse.runner.dag import WEEKLY_STAGES
    from pulse.runner.run import Runner, WarehouseSink, new_run_id
    from pulse.warehouse import connect, init_warehouse

    # Rebuild the warehouse only: publishing every historical week would be wasted work.
    skip = STATE_STAGES | {"narrate", "export", "publish_sheets"}
    stages = [
        replace(s, depends_on=tuple(d for d in s.depends_on if d not in skip))
        for s in WEEKLY_STAGES
        if s.name not in skip
    ]
    warehouse = ctx.data_dir / WAREHOUSE_FILE
    runner = Runner(
        stages, data_dir=ctx.data_dir, sinks=[WarehouseSink(warehouse)], clock=ctx.clock
    )
    for week in weeks:
        con = connect(warehouse)
        try:
            init_warehouse(con)
            existing = {r.run_id for r in meta.get_run_log(con)}
        finally:
            con.close()
        report = runner.run(week, RunType.BACKFILL, new_run_id(RunType.BACKFILL, week, existing))
        if report.failed:
            return StageResult(
                StageStatus.FAILED, message=f"Cold rebuild failed at {week} ({report.run_id})."
            )
    return StageResult(rows_out=len(weeks))


def clear_local(data_dir: Path) -> None:
    """Cold start begins from nothing so the rebuild is deterministic."""
    for name in (WAREHOUSE_FILE, f"{WAREHOUSE_FILE}.wal"):
        (data_dir / name).unlink(missing_ok=True)
    for name in (SOURCES_DIR, "defects", "narratives", "exports", "dbt-target"):
        shutil.rmtree(data_dir / name, ignore_errors=True)
    (data_dir / "defects.json").unlink(missing_ok=True)


def _run_ids(warehouse: Path) -> list[str]:
    from pulse.ingest import meta
    from pulse.warehouse import connect

    con = connect(warehouse, read_only=True)
    try:
        return sorted({r.run_id for r in meta.get_run_log(con)})
    finally:
        con.close()


class StateSync:
    """Holds the lock token between restore_state and release_lock of the same run."""

    def __init__(
        self,
        store_factory: StoreFactory = ObjectStore.from_env,
        *,
        rebuild: Rebuild = backfill_rebuild,
        start_week: str = START_WEEK,
        new_token: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self.store_factory = store_factory
        self.rebuild = rebuild
        self.start_week = start_week
        self.new_token = new_token
        self._tokens: dict[str, str] = {}
        # Runs that started from empty local state: their first persist prunes stale sources.
        self._fresh: set[str] = set()

    def _store(self) -> ObjectStore | None:
        store = self.store_factory()
        if store is None:
            log.warning("R2 credentials absent; state stays local.")
        return store

    def known_run_ids(self) -> set[str]:
        """Run ids already persisted to R2; empty without credentials or before the first run."""
        store = self.store_factory()
        try:
            found = store.get(RUNS_KEY) if store is not None else None
        except RetryableError as exc:
            # Safe: if R2 is down, restore_state fails too and this run persists nothing.
            log.warning("Could not read %s from R2: %s", RUNS_KEY, exc)
            return set()
        return set(json.loads(found[0])) if found else set()

    def restore(self, ctx: StageContext, *, skip_remote: bool = False) -> StageResult:
        store = self._store()
        if store is None:
            return StageResult(
                StageStatus.SKIPPED,
                message=f"R2 credentials absent; using local state in {ctx.data_dir}.",
            )

        token = self._tokens.setdefault(ctx.run_id, self.new_token())
        got = lock.acquire(store, ctx.run_id, token, ctx.clock.now())
        if isinstance(got, lock.Held):
            self._tokens.pop(ctx.run_id, None)
            until = got.holder.expires_at.strftime("%Y-%m-%d %H:%M UTC")
            return StageResult(
                StageStatus.SKIPPED,
                message=f"Run lock held by {got.holder.run_id} until {until}.",
                halt=True,
            )
        note = f" Took over expired lock from {got.took_over.run_id}." if got.took_over else ""

        if skip_remote:
            self._fresh.add(ctx.run_id)
            return StageResult(message=f"Rebuild starts from empty local state.{note}")

        if not store.exists(WAREHOUSE_FILE):
            # Narratives in R2 are left there: the rebuild narrates nothing, and mirroring
            # uploads only new or changed files, so the next persist cannot overwrite them.
            clear_local(ctx.data_dir)
            weeks = weeks_between(self.start_week, ctx.iso_week_id)
            if not weeks:
                return StageResult(message=f"Cold start: no state in R2.{note}")
            log.warning("No warehouse in R2: cold rebuild of %d weeks.", len(weeks))
            result = self.rebuild(ctx, weeks)
            if result.status is StageStatus.FAILED:
                return replace(result, message=f"Cold start: {result.message}{note}")
            return replace(
                result,
                message=(
                    f"Cold start: no state in R2. Rebuilt {len(weeks)} weeks "
                    f"({weeks[0]}..{weeks[-1]}).{note}"
                ),
            )

        sources = sorted(store.etags(f"{SOURCES_DIR}/"))
        for key in sources:
            store.download(key, ctx.data_dir / key)
        narratives = sorted(store.etags(f"{NARRATIVES_DIR}/"))
        for key in narratives:
            store.download(key, ctx.data_dir / key)
        # A WAL left by the local file would be replayed onto the restored one.
        (ctx.data_dir / f"{WAREHOUSE_FILE}.wal").unlink(missing_ok=True)
        store.download(WAREHOUSE_FILE, ctx.data_dir / WAREHOUSE_FILE)
        return StageResult(
            rows_out=len(sources),
            message=(
                f"Restored {WAREHOUSE_FILE}, {len(sources)} source files and "
                f"{len(narratives)} narrative files from R2.{note}"
            ),
        )

    def persist(self, ctx: StageContext) -> StageResult:
        store = self._store()
        if store is None:
            return StageResult(
                StageStatus.SKIPPED, message="R2 credentials absent; state stays local."
            )
        token = self._tokens.get(ctx.run_id)
        current = lock.holder(store)
        if token is None or current is None or current.token != token:
            by = f" (now held by {current.run_id})" if current else ""
            return StageResult(
                StageStatus.FAILED,
                message=f"This run does not hold the run lock{by}; not persisting.",
            )

        # Sources before the warehouse (see the module docstring), then the warehouse: the
        # checked week is what persist exists to keep. Narratives come last and are best effort,
        # so a failed upload of a page of text never costs the warehouse.
        sources = self._mirror(store, ctx.data_dir, SOURCES_DIR)
        pruned = ""
        if ctx.run_id in self._fresh:
            # A rebuild regenerates every source. Older files left in R2 would be restored and
            # ingested by the next week; they come from an older generator and break its joins.
            pruned = f", removed {self._prune(store, ctx.data_dir, SOURCES_DIR)} stale ones"
            self._fresh.discard(ctx.run_id)
        store.upload(ctx.data_dir / WAREHOUSE_FILE, WAREHOUSE_FILE)
        store.put(RUNS_KEY, json.dumps(_run_ids(ctx.data_dir / WAREHOUSE_FILE)).encode())
        persisted = f"Persisted {WAREHOUSE_FILE} and {sources} new or changed source files{pruned}"
        try:
            narratives = self._mirror(store, ctx.data_dir, NARRATIVES_DIR)
        except Exception as exc:  # any failure here must leave the warehouse kept
            log.warning("Narratives not persisted: %s", exc)
            return StageResult(
                StageStatus.WARN,
                rows_out=sources,
                message=f"{persisted}; narratives were not persisted ({type(exc).__name__}).",
            )
        message = f"{persisted}, plus {narratives} narrative files."
        return StageResult(rows_out=sources, message=message)

    @staticmethod
    def _mirror(store: ObjectStore, data_dir: Path, name: str) -> int:
        """Upload new or changed files under ``data_dir/name``; return how many."""
        remote = store.etags(f"{name}/")
        local_dir = data_dir / name
        files = sorted(p for p in local_dir.rglob("*") if p.is_file()) if local_dir.is_dir() else []
        uploaded = 0
        for path in files:
            key = path.relative_to(data_dir).as_posix()
            uploaded += store.upload_if_changed(path, key, remote.get(key))
        return uploaded

    @staticmethod
    def _prune(store: ObjectStore, data_dir: Path, name: str) -> int:
        """Delete remote files under ``name`` that ``data_dir/name`` lacks; return how many."""
        stale = [key for key in sorted(store.etags(f"{name}/")) if not (data_dir / key).is_file()]
        for key in stale:
            store.delete(key)
        return len(stale)

    def release(self, ctx: StageContext) -> StageResult:
        token = self._tokens.pop(ctx.run_id, None)
        if token is None:
            return StageResult(StageStatus.SKIPPED, message="No run lock held by this run.")
        store = self._store()
        if store is None:
            return StageResult(
                StageStatus.SKIPPED, message="R2 credentials absent; state stays local."
            )
        if lock.release(store, token):
            return StageResult(message="Released run lock.")
        return StageResult(StageStatus.WARN, message="Run lock was taken over before release.")
