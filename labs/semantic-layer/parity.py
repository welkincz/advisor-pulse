"""Semantic-layer parity (#322): MetricFlow results vs mart_org_weekly on fixtures.

Builds this lab's dbt project against the main project's fixture warehouse, runs one
`mf query` per org level (national, region, district, branch) by ISO week, and compares
every metric with the published mart value at the mart's own precision.

    uv run --project labs/semantic-layer python labs/semantic-layer/parity.py

Local, synthetic, single machine. Exit code 1 on any mismatch.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

LAB_DIR = Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
DEFAULT_WAREHOUSE = REPO_ROOT / "data" / "ci" / "warehouse.duckdb"

# MetricFlow metric -> (mart_org_weekly column, decimals the mart rounds to; None = exact).
METRICS: dict[str, tuple[str, int | None]] = {
    "portfolio_contacted_rate_12m": ("portfolio_contacted_rate_12m", 4),
    "portfolio_contacted_12m": ("portfolio_contacted_12m", None),
    "portfolio_clients": ("portfolio_clients", None),
    "activities_per_advisor": ("activities_per_advisor", 2),
    "activities_completed": ("activities_completed", None),
    "active_advisors": ("active_advisors", None),
    "show_rate": ("show_rate", 4),
    "appointments_held": ("appointments_held", None),
    "no_shows": ("no_shows", None),
    "calls_out": ("calls_out", None),
    "clients_contacted": ("unique_clients_contacted", None),
}

# Org level -> the group-by that produces it and the column that holds the node id.
LEVELS: dict[str, tuple[list[str], str | None]] = {
    "NATIONAL": (["metric_time__week"], None),
    "REGION": (["metric_time__week", "branch__region_code"], "branch__region_code"),
    "DISTRICT": (["metric_time__week", "branch__district_code"], "branch__district_code"),
    "BRANCH": (["metric_time__week", "branch"], "branch"),
}

LAB_FILES = ["dbt_project.yml", "profiles.yml", "models", "seeds"]


@dataclass
class Report:
    rows: dict[str, int] = field(default_factory=dict)
    cells: int = 0
    mismatches: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.mismatches


def copy_project(dest: Path) -> Path:
    """Copy the lab's dbt project (not its venv or target) so a test can mutate it."""
    for name in LAB_FILES:
        src = LAB_DIR / name
        if src.is_dir():
            shutil.copytree(src, dest / name)
        else:
            shutil.copy2(src, dest / name)
    return dest


def _env(project_dir: Path, warehouse: Path) -> dict[str, str]:
    return {
        **os.environ,
        "DBT_PROFILES_DIR": str(project_dir),
        "PULSE_CI_WAREHOUSE": str(warehouse),
        "SEMANTIC_LAB_DB": str(project_dir / "target" / "semantic_lab.duckdb"),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
    }


def _run(cmd: list[str], project_dir: Path, warehouse: Path) -> None:
    result = subprocess.run(
        cmd, cwd=project_dir, env=_env(project_dir, warehouse), capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{result.stdout}\n{result.stderr}")


def _bin(name: str) -> str:
    return str(Path(sys.executable).parent / name)


def build(project_dir: Path, warehouse: Path) -> None:
    _run([_bin("dbt"), "build", "--quiet"], project_dir, warehouse)


def mf_query(project_dir: Path, warehouse: Path, group_by: list[str], out: Path) -> list[dict]:
    cmd = [
        _bin("mf"),
        "query",
        "--metrics",
        ",".join(METRICS),
        "--group-by",
        ",".join(group_by),
        "--csv",
        str(out),
    ]
    _run(cmd, project_dir, warehouse)
    with out.open(newline="") as f:
        return list(csv.DictReader(f))


def _num(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)  # type: ignore[arg-type]


def _equal(semantic: float | None, mart: float | None, decimals: int | None) -> bool:
    if semantic is None or mart is None:
        return semantic is None and mart is None
    tolerance = 1e-9 if decimals is None else 0.5 * 10**-decimals + 1e-9
    return abs(semantic - mart) <= tolerance


def load_mart(warehouse: Path) -> tuple[dict[tuple[str, str, str], dict], dict[str, str]]:
    columns = ", ".join(col for col, _ in METRICS.values())
    with duckdb.connect(str(warehouse), read_only=True) as con:
        rows = con.sql(
            f"select level, node_id, iso_week_id, {columns} from marts.mart_org_weekly"
        ).fetchall()
        names = ["level", "node_id", "iso_week_id", *(col for col, _ in METRICS.values())]
        weeks = dict(
            con.sql(
                "select distinct cast(week_start as varchar), iso_week_id from marts.dim_date"
            ).fetchall()
        )
    mart = {}
    for row in rows:
        record = dict(zip(names, row, strict=True))
        mart[(record["level"], record["node_id"], record["iso_week_id"])] = record
    return mart, weeks


def compare(project_dir: Path = LAB_DIR, warehouse: Path = DEFAULT_WAREHOUSE) -> Report:
    report = Report()
    started = time.perf_counter()
    build(project_dir, warehouse)
    report.timings["dbt build (lab)"] = time.perf_counter() - started

    mart, weeks = load_mart(warehouse)
    seen: set[tuple[str, str, str]] = set()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        for level, (group_by, node_col) in LEVELS.items():
            rows = mf_query(project_dir, warehouse, group_by, Path(tmp) / f"{level}.csv")
            report.rows[level] = len(rows)
            for row in rows:
                week = weeks[row["metric_time__week"][:10]]
                node = row[node_col] if node_col else "CA"
                key = (level, node, week)
                seen.add(key)
                published = mart.get(key)
                if published is None:
                    report.mismatches.append(f"{key}: in MetricFlow, missing from the mart")
                    continue
                for metric, (column, decimals) in METRICS.items():
                    report.cells += 1
                    semantic, expected = _num(row[metric]), _num(published[column])
                    if not _equal(semantic, expected, decimals):
                        report.mismatches.append(
                            f"{key} {metric}: MetricFlow {semantic} != mart {expected}"
                        )
    report.timings["mf query x4 + compare"] = time.perf_counter() - started
    report.mismatches.extend(
        f"{key}: in the mart, missing from MetricFlow" for key in sorted(set(mart) - seen)
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--warehouse", type=Path, default=DEFAULT_WAREHOUSE)
    args = parser.parse_args()
    if not args.warehouse.exists():
        print(f"{args.warehouse} not found; run `make dbt-build-ci` first.", file=sys.stderr)
        return 2
    started = time.perf_counter()
    report = compare(LAB_DIR, args.warehouse.resolve())
    total = time.perf_counter() - started

    print("level     mf rows")
    for level, count in report.rows.items():
        print(f"{level:<9} {count:>7}")
    print(f"cells compared: {report.cells} ({len(METRICS)} metrics)")
    for name, seconds in report.timings.items():
        print(f"{name}: {seconds:.2f}s")
    print(f"total wall time: {total:.2f}s")
    if report.ok:
        print("PARITY OK: every MetricFlow value equals mart_org_weekly")
        return 0
    print(f"PARITY FAILED: {len(report.mismatches)} mismatches")
    for line in report.mismatches[:20]:
        print(f"  {line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
