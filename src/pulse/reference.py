"""Reference data: the fictional org hierarchy (``reference/org.yaml``) and activity types.

The loader validates the hierarchy on read, so every consumer (generator, dbt seeds, geo,
web) can rely on unique IDs, no orphans, and each branch FSA sitting in its district's
province(s).
"""

from __future__ import annotations

import csv
from datetime import date
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pulse.contracts import patterns
from pulse.contracts.enums import ActivityType, Province, RegionCode

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "reference"
ORG_PATH = REFERENCE_DIR / "org.yaml"
ACTIVITY_TYPES_PATH = REFERENCE_DIR / "activity_types.csv"

# Prince Edward Island has two branches, and a region is one province, so a district may be small.
MIN_BRANCHES_PER_DISTRICT = 2

# First letter of a postal code → province (Canada Post). X and Y (territories) are out of scope.
FSA_PROVINCE: dict[str, Province] = {
    "A": Province.NL,
    "B": Province.NS,
    "C": Province.PE,
    "E": Province.NB,
    "G": Province.QC,
    "H": Province.QC,
    "J": Province.QC,
    "K": Province.ON,
    "L": Province.ON,
    "M": Province.ON,
    "N": Province.ON,
    "P": Province.ON,
    "R": Province.MB,
    "S": Province.SK,
    "T": Province.AB,
    "V": Province.BC,
}


def fsa_province(fsa_code: str) -> Province:
    """Province of an FSA, from its first letter."""
    try:
        return FSA_PROVINCE[fsa_code[0]]
    except (IndexError, KeyError):
        raise ValueError(f"FSA {fsa_code!r} is not in a province in scope") from None


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Branch(_Frozen):
    branch_id: str = Field(pattern=patterns.BRANCH_ID)
    branch_name: str = Field(min_length=1)
    fsa_code: str = Field(pattern=patterns.FSA)
    open_date: date

    @property
    def province(self) -> Province:
        return fsa_province(self.fsa_code)


class District(_Frozen):
    district_code: str = Field(pattern=patterns.DISTRICT_CODE)
    district_name: str = Field(min_length=1)
    provinces: tuple[Province, ...] = Field(min_length=1)
    branches: tuple[Branch, ...] = Field(min_length=MIN_BRANCHES_PER_DISTRICT)

    @model_validator(mode="after")
    def _branches_in_district_provinces(self) -> District:
        for b in self.branches:
            if b.province not in self.provinces:
                raise ValueError(
                    f"{b.branch_id} FSA {b.fsa_code} is in {b.province}, "
                    f"not in district {self.district_code} {list(self.provinces)}"
                )
        return self


class Region(_Frozen):
    region_code: RegionCode
    region_name: str = Field(min_length=1)
    districts: tuple[District, ...] = Field(min_length=1)


class Bank(_Frozen):
    name: str = Field(min_length=1)
    fictional: bool

    @model_validator(mode="after")
    def _must_be_fictional(self) -> Bank:
        if not self.fictional:
            raise ValueError("The bank must be marked fictional")
        return self


class National(_Frozen):
    node_id: str = Field(pattern=r"^CA$")
    name: str = Field(min_length=1)


class BranchPlacement(_Frozen):
    """A branch with its place in the hierarchy."""

    branch: Branch
    district: District
    region: Region


class OrgReference(_Frozen):
    bank: Bank
    national: National
    regions: tuple[Region, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> OrgReference:
        id_lists: list[tuple[str, list[str]]] = [
            ("region_code", [str(r.region_code) for r in self.regions]),
            ("district_code", [d.district_code for d in self.districts]),
            ("branch_id", [b.branch_id for b in self.branches]),
        ]
        for label, ids in id_lists:
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            if dupes:
                raise ValueError(f"Duplicate {label}: {dupes}")
        if {r.region_code for r in self.regions} != set(RegionCode):
            raise ValueError("org.yaml must define every RegionCode exactly once")
        return self

    @property
    def districts(self) -> tuple[District, ...]:
        return tuple(d for r in self.regions for d in r.districts)

    @property
    def branches(self) -> tuple[Branch, ...]:
        return tuple(b for d in self.districts for b in d.branches)

    def placements(self) -> tuple[BranchPlacement, ...]:
        return tuple(
            BranchPlacement(branch=b, district=d, region=r)
            for r in self.regions
            for d in r.districts
            for b in d.branches
        )

    def placement(self, branch_id: str) -> BranchPlacement:
        for p in self.placements():
            if p.branch.branch_id == branch_id:
                return p
        raise KeyError(branch_id)

    def district(self, district_code: str) -> District:
        for d in self.districts:
            if d.district_code == district_code:
                return d
        raise KeyError(district_code)

    def region_of(self, district_code: str) -> Region:
        for r in self.regions:
            if any(d.district_code == district_code for d in r.districts):
                return r
        raise KeyError(district_code)


class ActivityTypeRef(_Frozen):
    activity_type: ActivityType
    label: str = Field(min_length=1)
    counts_as_contact: bool
    is_appointment_like: bool


def load_org(path: Path = ORG_PATH) -> OrgReference:
    with path.open(encoding="utf-8") as fh:
        return OrgReference.model_validate(yaml.safe_load(fh))


def load_activity_types(path: Path = ACTIVITY_TYPES_PATH) -> tuple[ActivityTypeRef, ...]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = tuple(ActivityTypeRef.model_validate(row) for row in csv.DictReader(fh))
    found = [r.activity_type for r in rows]
    if sorted(found) != sorted(ActivityType):
        raise ValueError(f"activity_types.csv must list each ActivityType once, got {found}")
    return rows


@cache
def org() -> OrgReference:
    """The committed org reference, loaded once per process."""
    return load_org()
