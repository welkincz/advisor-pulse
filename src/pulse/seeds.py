"""Export reference data and the business calendar to dbt seeds.

python -m pulse.seeds          # write dbt/seeds/*.csv
python -m pulse.seeds --check  # exit 1 if the committed CSVs are stale

``make seeds`` is the entry point. The org seed is one row per branch in
``reference/org.yaml``. Province letters are the Canada Post map in
``pulse.reference``. Boundary codes are the FSAs in the shipped StatCan layer. The
business week seed is ``pulse.business_calendar.week_factor`` for every ISO week that
``dim_date`` covers by default, so the report's anomaly rule uses the same calendar as the
generator and DQ031.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pulse.business_calendar import week_factor
from pulse.contracts.enums import Province
from pulse.reference import FSA_PROVINCE, org

ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "dbt" / "seeds"
BOUNDARY_PATH = ROOT / "web" / "public" / "geo" / "fsa.topo.json"

PROVINCE_NAME: dict[Province, str] = {
    Province.ON: "Ontario",
    Province.QC: "Quebec",
    Province.BC: "British Columbia",
    Province.AB: "Alberta",
    Province.SK: "Saskatchewan",
    Province.MB: "Manitoba",
    Province.NS: "Nova Scotia",
    Province.PE: "Prince Edward Island",
    Province.NB: "New Brunswick",
    Province.NL: "Newfoundland and Labrador",
}

ORG_BRANCH_COLUMNS = (
    "branch_id",
    "branch_name",
    "district_code",
    "district_name",
    "region_code",
    "region_name",
    "fsa_code",
    "province_code",
    "open_date",
)
FSA_PROVINCE_COLUMNS = ("fsa_first_letter", "province_code", "province_name")
FSA_BOUNDARY_COLUMNS = ("fsa_code",)
BUSINESS_WEEK_COLUMNS = ("iso_week_id", "week_factor")
# dim_date's default range (dbt vars dim_date_start and dim_date_end).
DIM_DATE_START, DIM_DATE_END = date(2023, 1, 1), date(2027, 12, 31)


def _csv(columns: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def org_branch_rows() -> list[dict[str, str]]:
    """One row per branch, in org.yaml order."""
    return [
        {
            "branch_id": place.branch.branch_id,
            "branch_name": place.branch.branch_name,
            "district_code": place.district.district_code,
            "district_name": place.district.district_name,
            "region_code": place.region.region_code.value,
            "region_name": place.region.region_name,
            "fsa_code": place.branch.fsa_code,
            "province_code": place.branch.province.value,
            "open_date": place.branch.open_date.isoformat(),
        }
        for place in org().placements()
    ]


def fsa_province_rows() -> list[dict[str, str]]:
    """First letter of an FSA → province. Sorted by letter."""
    if set(PROVINCE_NAME) != set(Province):
        raise RuntimeError("PROVINCE_NAME must name every Province")
    return [
        {
            "fsa_first_letter": letter,
            "province_code": province.value,
            "province_name": PROVINCE_NAME[province],
        }
        for letter, province in sorted(FSA_PROVINCE.items())
    ]


def boundary_codes(path: Path = BOUNDARY_PATH) -> list[str]:
    """FSA codes in the shipped TopoJSON, sorted."""
    if not path.is_file():
        raise FileNotFoundError(f"Missing shipped FSA boundaries: {path}")
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    geometries: list[Any] = payload["objects"]["fsa"]["geometries"]
    codes = [str(geometry["properties"]["CFSAUID"]) for geometry in geometries]
    if len(codes) != len(set(codes)):
        raise ValueError(f"Duplicate FSA in {path}")
    return sorted(codes)


def business_week_rows(
    start: date = DIM_DATE_START, end: date = DIM_DATE_END
) -> list[dict[str, str]]:
    """One row per ISO week touching ``start``..``end``, with the calendar's expected
    volume relative to an ordinary week. ``repr`` keeps the float exact."""
    monday = start - timedelta(days=start.weekday())
    rows = []
    while monday <= end:
        iso = monday.isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        rows.append({"iso_week_id": week, "week_factor": repr(week_factor(week))})
        monday += timedelta(weeks=1)
    return rows


def render_seeds() -> dict[str, str]:
    """CSV text for each seed file, keyed by file name."""
    return {
        "org_branch.csv": _csv(ORG_BRANCH_COLUMNS, org_branch_rows()),
        "fsa_province.csv": _csv(FSA_PROVINCE_COLUMNS, fsa_province_rows()),
        "fsa_boundary.csv": _csv(
            FSA_BOUNDARY_COLUMNS, [{"fsa_code": code} for code in boundary_codes()]
        ),
        "business_week.csv": _csv(BUSINESS_WEEK_COLUMNS, business_week_rows()),
    }


def write_seeds(directory: Path | None = None) -> dict[str, str]:
    rendered = render_seeds()
    target = SEED_DIR if directory is None else directory
    target.mkdir(parents=True, exist_ok=True)
    for name, body in rendered.items():
        (target / name).write_text(body, encoding="utf-8")
    return rendered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--check", action="store_true", help="Fail if committed seeds are stale.")
    args = parser.parse_args(argv)
    rendered = render_seeds()
    stale = [
        name
        for name, body in rendered.items()
        if not (SEED_DIR / name).is_file() or (SEED_DIR / name).read_text(encoding="utf-8") != body
    ]
    if args.check:
        if stale:
            print("dbt seeds are stale (run `make seeds`): " + ", ".join(stale), file=sys.stderr)
            return 1
        print(f"dbt seeds are up to date ({len(rendered)} files).")
        return 0
    write_seeds()
    for name in rendered:
        print(f"Wrote dbt/seeds/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
