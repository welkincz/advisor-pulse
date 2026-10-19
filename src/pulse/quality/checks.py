"""Read fixture-backed warehouse inputs and persist DQ030–DQ033 run checks."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import duckdb

from pulse.business_calendar import week_factor
from pulse.contracts.defects import DefectManifest
from pulse.contracts.enums import CheckStatus, LoadStatus, StageStatus
from pulse.ingest import meta
from pulse.quality.policy import (
    CheckPolicy,
    defect_reconciliation,
    freshness,
    quarantine_rate,
    volume,
)
from pulse.runner.stage import StageResult
from pulse.warehouse import transaction

EXTRACT_DATE = re.compile(r"extract_date=(\d{4}-\d{2}-\d{2})")


def first_reported_week(files: list[str]) -> str | None:
    """ISO week of the earliest activity extract loaded, or None if none is.

    Weeks before it hold only late rows that the first extract carried back (1–3 weeks),
    so they are partial and must not enter the DQ031 baseline.
    """
    dates = sorted(m.group(1) for path in files if (m := EXTRACT_DATE.search(path)))
    if not dates:
        return None
    first = date.fromisoformat(dates[0]).isocalendar()
    return f"{first.year}-W{first.week:02d}"


def run_checks(
    warehouse: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    iso_week_id: str,
    defect_manifest: DefectManifest,
    policy_path: Path | None = Path("pulse.toml"),
    ci: bool = False,
) -> StageResult:
    """Write four check results and return a stage result for runner dependency gating."""
    policy = CheckPolicy.from_toml(policy_path)
    year, week = iso_week_id.split("-W")
    week_end = date.fromisocalendar(int(year), int(week), 7)
    baseline_monday = week_end - timedelta(days=6, weeks=8)
    baseline_week = (
        f"{baseline_monday.isocalendar().year}-W{baseline_monday.isocalendar().week:02d}"
    )
    latest_row = warehouse.execute(
        "SELECT max(CAST(ACTIVITY_TS AT TIME ZONE 'America/Toronto' AS DATE)) "
        "FROM raw.snowflake__activity "
        "WHERE CAST(ACTIVITY_TS AT TIME ZONE 'America/Toronto' AS DATE) <= ?",
        [week_end],
    ).fetchone()
    latest = latest_row[0] if latest_row else None
    national = warehouse.execute(
        "SELECT iso_week_id, activities_completed FROM marts.mart_org_weekly "
        "WHERE level = 'NATIONAL' AND node_id = 'CA' "
        "AND iso_week_id BETWEEN ? AND ? ORDER BY iso_week_id DESC",
        [baseline_week, iso_week_id],
    ).fetchall()
    loaded = [entry for entry in meta.get_manifest(warehouse) if entry.status is LoadStatus.LOADED]
    first_week = first_reported_week([entry.file_path for entry in loaded]) or ""
    current = next((int(count) for week_id, count in national if week_id == iso_week_id), None)
    prior = [(w, int(count)) for w, count in national if first_week <= w < iso_week_id][:8]
    history = [count for _, count in prior]
    history_factors = [week_factor(w) for w, _ in prior]
    batches = [entry for entry in loaded if entry.run_id == run_id]
    rows_in = sum(entry.row_count for entry in batches)
    quarantined = sum(entry.rows_quarantined for entry in batches)
    relevant_rules = {f"DQ00{i}" for i in range(1, 6)}
    expected_files = {
        defect.file
        for defect in defect_manifest.defects
        if defect.iso_week_id == iso_week_id and defect.rule_id in relevant_rules
    }
    scope_files = {entry.file_path for entry in batches} | expected_files
    expected: set[tuple[str, int | None, str | None]] = {
        (d.file, d.row, d.rule_id)
        for d in defect_manifest.defects
        if d.file in scope_files and d.rule_id in relevant_rules
    }
    latest_by_file = {
        file: max(
            (entry for entry in loaded if entry.file_path == file),
            key=lambda entry: (entry.loaded_at, entry.run_id == run_id),
            default=None,
        )
        for file in scope_files
    }
    active_batches = {entry.batch_id for entry in latest_by_file.values() if entry is not None}
    actual: set[tuple[str, int | None, str | None]] = {
        (r.source_file, r.source_row, r.rule_id)
        for r in meta.get_rejected_rows(warehouse)
        if r.batch_id in active_batches and r.rule_id in relevant_rules
    }
    checks = [
        freshness(run_id, iso_week_id, latest, policy),
        volume(
            run_id,
            current,
            history,
            policy,
            current_factor=week_factor(iso_week_id),
            history_factors=history_factors,
        ),
        quarantine_rate(run_id, quarantined, rows_in, policy),
        defect_reconciliation(run_id, expected, actual, policy, ci=ci),
    ]
    with transaction(warehouse):
        for check in checks:
            meta.write_check_result(warehouse, check)
    status = (
        StageStatus.FAILED
        if any(c.status is CheckStatus.FAIL for c in checks)
        else StageStatus.WARN
        if any(c.status is CheckStatus.WARN for c in checks)
        else StageStatus.SUCCESS
    )
    exceptions = ", ".join(
        f"{c.check_id} {c.status.value}" for c in checks if c.status is not CheckStatus.PASS
    )
    return StageResult(status, message=exceptions or "All four run checks passed")
