from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from pulse.contracts import patterns
from pulse.contracts.enums import ActivityType, Province, RegionCode
from pulse.reference import (
    ACTIVITY_TYPES_PATH,
    ORG_PATH,
    OrgReference,
    fsa_province,
    load_activity_types,
    load_org,
    org,
)

# ── The committed org.yaml ───────────────────────────────────────────────────


def test_shape_matches_plan() -> None:
    o = org()
    assert [r.region_code for r in o.regions] == list(RegionCode)
    assert len(o.districts) == 17
    assert 110 <= len(o.branches) <= 130
    assert o.national.node_id == "CA"
    assert o.bank.fictional


def test_district_names_match_plan() -> None:
    expected = {
        "ON": ["GTA", "Eastern Ontario", "Southwestern Ontario", "Northern Ontario"],
        "QC": ["Greater Montréal", "Québec City & East", "Western Quebec"],
        "BC": ["BC Lower Mainland", "BC Interior & North"],
        "AB": ["Calgary & Southern Alberta", "Edmonton & Northern Alberta"],
        "SK": ["Saskatchewan"],
        "MB": ["Manitoba"],
        "NS": ["Nova Scotia"],
        "PE": ["Prince Edward Island"],
        "NB": ["New Brunswick"],
        "NL": ["Newfoundland & Labrador"],
    }
    actual = {r.region_code.value: [d.district_name for d in r.districts] for r in org().regions}
    assert actual == expected


def test_every_district_has_at_least_two_branches() -> None:
    # Prince Edward Island, a region of its own, has two.
    assert min(len(d.branches) for d in org().districts) >= 2


def test_every_region_is_one_province() -> None:
    for r in org().regions:
        assert {p for d in r.districts for p in d.provinces} == {r.region_code.value}


def test_ids_are_unique_and_well_formed() -> None:
    o = org()
    ids = [b.branch_id for b in o.branches]
    assert len(ids) == len(set(ids))
    assert all(re.match(patterns.BRANCH_ID, i) for i in ids)
    codes = [d.district_code for d in o.districts]
    assert len(codes) == len(set(codes))
    assert all(re.match(patterns.DISTRICT_CODE, c) for c in codes)


def test_branch_ids_encode_district_order() -> None:
    for d_no, d in enumerate(org().districts, start=1):
        assert all(b.branch_id.startswith(f"BR-{d_no:02d}") for b in d.branches)


def test_every_fsa_is_valid_and_in_its_district_province() -> None:
    for d in org().districts:
        for b in d.branches:
            assert re.match(patterns.FSA, b.fsa_code), b.branch_id
            assert fsa_province(b.fsa_code) in d.provinces, b.branch_id


def test_gta_branches_are_in_toronto_area_fsas() -> None:
    gta = org().district("GTA")
    assert all(b.fsa_code[0] in "ML" for b in gta.branches)


def test_branch_counts_follow_population() -> None:
    by_region = {r.region_code: sum(len(d.branches) for d in r.districts) for r in org().regions}
    assert (
        by_region[RegionCode.ONTARIO]
        > by_region[RegionCode.QUEBEC]
        > by_region[RegionCode.BRITISH_COLUMBIA]
        > by_region[RegionCode.ALBERTA]
        > by_region[RegionCode.PRINCE_EDWARD_ISLAND]
    )
    largest = max(org().districts, key=lambda d: len(d.branches))
    assert largest.district_code == "GTA"


def test_every_branch_predates_the_simulation_window() -> None:
    # 104 weeks of history start in late 2024; branches must already be open.
    assert max(b.open_date.year for b in org().branches) < 2024


def test_lookups() -> None:
    o = org()
    p = o.placement("BR-0101")
    assert (p.district.district_code, p.region.region_code) == ("GTA", RegionCode.ONTARIO)
    assert o.region_of("SKD").region_code == RegionCode.SASKATCHEWAN
    assert len(o.placements()) == len(o.branches)
    with pytest.raises(KeyError):
        o.placement("BR-9999")


def test_codes_survive_yaml_1_1() -> None:
    # A bare ON parses as a boolean in YAML 1.1; every code must load as a string.
    raw = yaml.safe_load(ORG_PATH.read_text(encoding="utf-8"))
    assert raw["regions"][0]["region_code"] == "ON"
    assert raw["regions"][0]["districts"][0]["provinces"] == ["ON"]


# ── Validation rules, on mutated copies ─────────────────────────────────────


@pytest.fixture
def raw_org() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(ORG_PATH.read_text(encoding="utf-8"))
    return data


def _first_district(raw: dict[str, Any]) -> dict[str, Any]:
    district: dict[str, Any] = raw["regions"][0]["districts"][0]
    return district


def test_duplicate_branch_id_rejected(raw_org: dict[str, Any]) -> None:
    branches = _first_district(raw_org)["branches"]
    branches[1]["branch_id"] = branches[0]["branch_id"]
    with pytest.raises(ValidationError, match="Duplicate branch_id"):
        OrgReference.model_validate(raw_org)


def test_duplicate_district_code_rejected(raw_org: dict[str, Any]) -> None:
    raw_org["regions"][1]["districts"][0]["district_code"] = "GTA"
    with pytest.raises(ValidationError, match="Duplicate district_code"):
        OrgReference.model_validate(raw_org)


def test_fsa_in_wrong_province_rejected(raw_org: dict[str, Any]) -> None:
    _first_district(raw_org)["branches"][0]["fsa_code"] = "H3B"  # Montréal FSA in the GTA
    with pytest.raises(ValidationError, match="not in district GTA"):
        OrgReference.model_validate(raw_org)


def test_district_with_too_few_branches_rejected(raw_org: dict[str, Any]) -> None:
    d = _first_district(raw_org)
    d["branches"] = d["branches"][:1]
    with pytest.raises(ValidationError):
        OrgReference.model_validate(raw_org)


def test_missing_region_rejected(raw_org: dict[str, Any]) -> None:
    raw_org["regions"] = raw_org["regions"][:3]
    with pytest.raises(ValidationError, match="every RegionCode"):
        OrgReference.model_validate(raw_org)


def test_non_fictional_bank_rejected(raw_org: dict[str, Any]) -> None:
    raw_org["bank"]["fictional"] = False
    with pytest.raises(ValidationError, match="fictional"):
        OrgReference.model_validate(raw_org)


def test_unknown_key_rejected(raw_org: dict[str, Any]) -> None:
    _first_district(raw_org)["manager"] = "someone"
    with pytest.raises(ValidationError):
        OrgReference.model_validate(raw_org)


def test_load_org_reads_a_path(tmp_path: Path, raw_org: dict[str, Any]) -> None:
    path = tmp_path / "org.yaml"
    path.write_text(yaml.safe_dump(raw_org, allow_unicode=True), encoding="utf-8")
    assert len(load_org(path).branches) == len(org().branches)


@pytest.mark.parametrize(
    ("fsa", "province"),
    [("M5V", Province.ON), ("H3B", Province.QC), ("V6B", Province.BC), ("A1C", Province.NL)],
)
def test_fsa_province(fsa: str, province: Province) -> None:
    assert fsa_province(fsa) == province


@pytest.mark.parametrize("fsa", ["X0A", "Y1A", ""])
def test_fsa_province_out_of_scope(fsa: str) -> None:
    with pytest.raises(ValueError):
        fsa_province(fsa)


# ── activity_types.csv ──────────────────────────────────────────────────────


def test_activity_types_match_plan() -> None:
    rows = {r.activity_type: r for r in load_activity_types()}
    assert set(rows) == set(ActivityType)
    assert all(r.counts_as_contact for r in rows.values())
    assert {t for t, r in rows.items() if r.is_appointment_like} == {
        ActivityType.APPOINTMENT,
        ActivityType.REVIEW,
    }


def test_activity_types_reject_missing_type(tmp_path: Path) -> None:
    lines = ACTIVITY_TYPES_PATH.read_text(encoding="utf-8").splitlines()
    path = tmp_path / "activity_types.csv"
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="each ActivityType once"):
        load_activity_types(path)
