"""Write the Actions stage table and check artifact even when a run fails early."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def selected_runs(runs: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "weekly":
        return next(([r] for r in runs if r["run_type"] == "WEEKLY"), [])
    first, last = os.environ["FROM_WEEK"], os.environ["TO_WEEK"]
    latest: dict[str, dict[str, Any]] = {}
    for run in runs:  # run_log is newest first; retain the latest attempt per week.
        week = run["iso_week_id"]
        if run["run_type"] == "BACKFILL" and first <= week <= last:
            latest.setdefault(week, run)
    return [latest[week] for week in sorted(latest)]


def table(run: dict[str, Any]) -> list[str]:
    lines = [
        "| Stage | Attempt | Status | In | Out | Quarantined | Duration ms |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for stage in run["stages"]:
        cells = [
            stage["stage"],
            stage["attempt"],
            stage["status"],
            stage.get("rows_in"),
            stage.get("rows_out"),
            stage.get("rows_quarantined"),
            stage.get("duration_ms"),
        ]
        lines.append("| " + " | ".join(str(v) if v is not None else "—" for v in cells) + " |")
    return lines


def main(mode: str) -> None:
    root = Path(os.environ["PULSE_DATA_DIR"])
    log = root / "exports" / "run_log.json"
    runs = json.loads(log.read_text())["runs"] if log.exists() else []
    chosen = selected_runs(runs, mode)
    artifact = root / "artifacts" / "check_results.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {"runs": [{"run_id": run["run_id"], "checks": run["checks"]} for run in chosen]},
            indent=2,
        )
        + "\n"
    )

    lines = [
        "## Weekly report"
        if mode == "weekly"
        else f"## Backfill {os.environ['FROM_WEEK']} to {os.environ['TO_WEEK']}"
    ]
    if not chosen:
        lines.append("No run log was produced; inspect the failed setup or run step.")
    for run in chosen:
        lines += [
            f"### {run['iso_week_id']} · {run['run_id']} · {run['status']}",
            "",
            *table(run),
            "",
        ]
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
        summary.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
