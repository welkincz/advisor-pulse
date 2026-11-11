"""The dbt seeds are a pure export of org.yaml, the shipped FSA layer and the business
calendar."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

from pulse.business_calendar import week_factor
from pulse.contracts.enums import Province
from pulse.reference import FSA_PROVINCE, org
from pulse.seeds import (
    BOUNDARY_PATH,
    DIM_DATE_END,
    DIM_DATE_START,
    PROVINCE_NAME,
    SEED_DIR,
    business_week_rows,
    fsa_province_rows,
    main,
    org_branch_rows,
    render_seeds,
    write_seeds,
)


def _rows(name: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(render_seeds()[name])))


def test_org_branch_matches_org_yaml() -> None:
    rows = org_branch_rows()
    placements = org().placements()
    assert len(rows) == len(placements)
    assert rows == _rows("org_branch.csv")
    for row, place in zip(rows, placements, strict=True):
        assert row["branch_id"] == place.branch.branch_id
        assert row["branch_name"] == place.branch.branch_name
        assert row["district_code"] == place.district.district_code
        assert row["district_name"] == place.district.district_name
        assert row["region_code"] == place.region.region_code.value
        assert row["region_name"] == place.region.region_name
        assert row["fsa_code"] == place.branch.fsa_code
        assert row["province_code"] == place.branch.province.value
        assert row["open_date"] == place.branch.open_date.isoformat()
        assert row["district_code"] and row["region_code"]


def test_each_district_has_one_hierarchy() -> None:
    seen: dict[str, set[tuple[str, str, str]]] = {}
    for row in org_branch_rows():
        seen.setdefault(row["district_code"], set()).add(
            (row["district_name"], row["region_code"], row["region_name"])
        )
    assert seen
    assert all(len(names) == 1 for names in seen.values())


def test_fsa_province_seed_is_the_canada_post_map() -> None:
    assert set(PROVINCE_NAME) == set(Province)
    rows = fsa_province_rows()
    assert [row["fsa_first_letter"] for row in rows] == sorted(FSA_PROVINCE)
    for row in rows:
        province = FSA_PROVINCE[row["fsa_first_letter"]]
        assert row["province_code"] == province.value
        assert row["province_name"] == PROVINCE_NAME[province]


def test_boundary_seed_matches_shipped_topojson() -> None:
    codes = [row["fsa_code"] for row in _rows("fsa_boundary.csv")]
    payload = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
    shipped = sorted(
        geometry["properties"]["CFSAUID"] for geometry in payload["objects"]["fsa"]["geometries"]
    )
    assert codes == shipped


def test_committed_seeds_match_render(tmp_path: Path) -> None:
    rendered = render_seeds()
    for name, body in rendered.items():
        assert (SEED_DIR / name).read_text(encoding="utf-8") == body
    assert main(["--check"]) == 0
    assert write_seeds(tmp_path) == rendered


def test_business_week_seed_is_the_calendar_the_generator_and_dq031_use() -> None:
    rows = _rows("business_week.csv")
    assert rows == business_week_rows()
    for row in rows:
        assert float(row["week_factor"]) == week_factor(row["iso_week_id"])
    # Labour Day 2026 and the February lift are not ordinary weeks.
    by_week = {row["iso_week_id"]: float(row["week_factor"]) for row in rows}
    assert by_week["2026-W37"] < 1.0 < by_week["2026-W07"]
    assert by_week["2026-W36"] == 1.0


def test_business_week_seed_covers_dim_dates_default_range() -> None:
    sql = (SEED_DIR.parent / "models" / "marts" / "dim_date.sql").read_text(encoding="utf-8")
    defaults = dict(re.findall(r'var\("(dim_date_start|dim_date_end)", "([0-9-]+)"\)', sql))
    assert defaults == {
        "dim_date_start": DIM_DATE_START.isoformat(),
        "dim_date_end": DIM_DATE_END.isoformat(),
    }
    weeks = [row["iso_week_id"] for row in business_week_rows()]
    iso = DIM_DATE_START.isocalendar()
    assert weeks[0] == f"{iso.year}-W{iso.week:02d}"
    iso = DIM_DATE_END.isocalendar()
    assert weeks[-1] == f"{iso.year}-W{iso.week:02d}"
    assert len(weeks) == len(set(weeks))
