"""The dbt_build, checks and export stages of the weekly DAG.

Each one reads ``ctx.data_dir`` only. Before any activity is loaded, checks and export
find the marts missing or empty and report SKIPPED instead of failing the run.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from pulse.contracts.defects import DefectManifest
from pulse.contracts.enums import StageStatus
from pulse.contracts.exports import EXPORT_TABLE_CONTRACTS, NarrativeFile
from pulse.runner.stage import StageContext, StageResult
from pulse.warehouse import WAREHOUSE_FILE, connect, init_warehouse

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DBT_DIR = REPO_ROOT / "dbt"
POLICY_FILE = REPO_ROOT / "pulse.toml"
DEFECTS_FILE = "defects.json"
NARRATIVES_DIR = "narratives"
DBT_TARGET_DIR = "dbt-target"
EXPORT_DIR_ENV = "PULSE_EXPORT_DIR"
DEFAULT_EXPORT_DIR = REPO_ROOT / "web" / "public" / "data"
ORG_MART = ("marts", "mart_org_weekly")


def _has_table(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> bool:
    row = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
        [schema, table],
    ).fetchone()
    return bool(row and row[0])


# ── dbt_build ───────────────────────────────────────────────────────────────

DbtCommand = Callable[[StageContext, Path], Sequence[str]]


def dbt_command(ctx: StageContext, target_path: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "dbt.cli.main",
        "--no-use-colors",
        "build",
        "--project-dir",
        str(DBT_DIR),
        "--profiles-dir",
        str(DBT_DIR),
        "--target",
        "dev",
        "--target-path",
        str(target_path.resolve()),
    ]


@dataclass(frozen=True)
class DbtOutcome:
    failed: list[str]
    warned: list[str]
    total: int


def read_run_results(path: Path) -> DbtOutcome:
    """Node names by status from dbt's ``run_results.json``."""
    results = json.loads(path.read_text(encoding="utf-8"))["results"]
    failed = sorted(r["unique_id"] for r in results if r["status"] in {"error", "fail"})
    warned = sorted(r["unique_id"] for r in results if r["status"] == "warn")
    return DbtOutcome(failed, warned, len(results))


def _names(ids: Sequence[str], limit: int = 5) -> str:
    short = [i.split(".", 2)[-1] for i in ids]
    more = f" (+{len(short) - limit} more)" if len(short) > limit else ""
    return ", ".join(short[:limit]) + more


def dbt_build(ctx: StageContext, command: DbtCommand = dbt_command) -> StageResult:
    """``dbt build --target dev`` against this run's warehouse. dbt warnings make it WARN."""
    target_path = ctx.data_dir / DBT_TARGET_DIR
    results_file = target_path / "run_results.json"
    results_file.unlink(missing_ok=True)
    # The dev profile reads the warehouse at $PULSE_DATA_DIR; dbt also needs it to exist.
    con = connect(ctx.data_dir / WAREHOUSE_FILE)
    try:
        init_warehouse(con)
    finally:
        con.close()
    env = {**os.environ, "PULSE_DATA_DIR": str(ctx.data_dir.resolve())}
    proc = subprocess.run(
        list(command(ctx, target_path)),
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if not results_file.exists():
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
        return StageResult(
            StageStatus.FAILED,
            message=f"dbt build exited {proc.returncode} before running nodes: {' | '.join(tail)}",
        )
    outcome = read_run_results(results_file)
    if outcome.failed or proc.returncode != 0:
        return StageResult(
            StageStatus.FAILED,
            rows_out=outcome.total,
            message=f"dbt build failed: {_names(outcome.failed) or f'exit {proc.returncode}'}.",
        )
    if outcome.warned:
        return StageResult(
            StageStatus.WARN,
            rows_out=outcome.total,
            message=f"{outcome.total} dbt nodes; {len(outcome.warned)} warned: "
            f"{_names(outcome.warned)}.",
        )
    return StageResult(rows_out=outcome.total, message=f"{outcome.total} dbt nodes passed.")


# ── checks ──────────────────────────────────────────────────────────────────


def load_defects(data_dir: Path, iso_week_id: str, now: datetime) -> DefectManifest:
    """The generator's defect manifest, or an empty one (no defects expected) if absent."""
    weekly = data_dir / "defects" / f"{iso_week_id}.json"
    path = weekly if weekly.exists() else data_dir / DEFECTS_FILE
    if path.exists():
        return DefectManifest.model_validate_json(path.read_text(encoding="utf-8"))
    log.warning("No %s in %s: expecting no injected defects.", DEFECTS_FILE, data_dir)
    return DefectManifest(generated_at=now, seed=0, iso_weeks=[iso_week_id], defects=[])


def checks(ctx: StageContext, policy_path: Path | None = POLICY_FILE) -> StageResult:
    if os.environ.get("PULSE_FORCE_FAIL") == "checks":
        return StageResult(
            StageStatus.FAILED, message="Checks stage forced to fail for alert test."
        )
    from pulse.quality.checks import run_checks

    con = connect(ctx.data_dir / WAREHOUSE_FILE)
    try:
        init_warehouse(con)
        if not _has_table(con, *ORG_MART):
            return StageResult(StageStatus.SKIPPED, message="marts.mart_org_weekly not built yet.")
        if con.execute("SELECT count(*) FROM marts.mart_org_weekly").fetchone() == (0,):
            # Nothing has been loaded yet, so there is no week to judge; stale data still fails.
            return StageResult(StageStatus.SKIPPED, message="No activity loaded yet.")
        manifest = load_defects(ctx.data_dir, ctx.iso_week_id, ctx.clock.now())
        return run_checks(
            con,
            run_id=ctx.run_id,
            iso_week_id=ctx.iso_week_id,
            defect_manifest=manifest,
            policy_path=policy_path,
        )
    finally:
        con.close()


# ── export ──────────────────────────────────────────────────────────────────


def export_dir() -> Path:
    return Path(os.environ.get(EXPORT_DIR_ENV) or DEFAULT_EXPORT_DIR)


def load_narratives(data_dir: Path) -> dict[str, NarrativeFile]:
    """Every week's narrative written so far: the site keeps the full history."""
    folder = data_dir / NARRATIVES_DIR
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    return {p.stem: NarrativeFile.model_validate_json(p.read_text(encoding="utf-8")) for p in files}


def export(ctx: StageContext) -> StageResult:
    """Publish the weekly report. An ``always`` stage: after a failure it publishes only
    ``run_log.json``, so the site says the last run failed and keeps the previous week."""
    from pulse.export.pipeline_graph import build_pipeline_graph, read_manifest
    from pulse.export.web import export_web
    from pulse.runner.dag import WEEKLY_STAGES
    from pulse.runner.run_log import export_from_warehouse

    now = ctx.clock.now()
    con = connect(ctx.data_dir / WAREHOUSE_FILE)
    try:
        init_warehouse(con)
        run_log = export_from_warehouse(con, generated_at=now, current_run_id=ctx.run_id)
        current = run_log.runs[0] if run_log.runs else None
        if current is None or current.run_id != ctx.run_id:
            raise RuntimeError(f"run_log has no rows for {ctx.run_id}")
        failed = current.status is StageStatus.FAILED
        if not failed:
            missing = [
                f"mart_{m.contract_name}"
                for m in EXPORT_TABLE_CONTRACTS
                if not _has_table(con, "marts", f"mart_{m.contract_name}")
            ]
            if missing:
                return StageResult(
                    StageStatus.SKIPPED, message=f"Marts not built yet: {', '.join(missing)}."
                )
            if con.execute("SELECT count(*) FROM marts.mart_org_weekly").fetchone() == (0,):
                return StageResult(StageStatus.SKIPPED, message="No activity loaded yet.")
        manifest = export_web(
            con,
            export_dir(),
            run_log=run_log,
            pipeline_graph=build_pipeline_graph(
                WEEKLY_STAGES, read_manifest(ctx.data_dir / DBT_TARGET_DIR / "manifest.json")
            ),
            narratives=load_narratives(ctx.data_dir),
            run_id=ctx.run_id,
            generated_at=now,
            has_fsa_boundaries=(REPO_ROOT / "web" / "public" / "geo" / "fsa.topo.json").exists(),
        )
    finally:
        con.close()
    if manifest is None:
        return StageResult(
            StageStatus.WARN, message="Run failed: published run_log.json only; data unchanged."
        )
    return StageResult(
        rows_out=len(manifest.files),
        message=f"Exported {len(manifest.files)} files for {manifest.latest_week}.",
    )
