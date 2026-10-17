"""District and region polygons dissolved from the shipped FSA layer (issue #32)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from pulse.contracts.enums import RegionCode
from pulse.reference import org

ROOT = Path(__file__).resolve().parents[1]
_BUILD_SPEC = importlib.util.spec_from_file_location(
    "geo_build_boundaries", ROOT / "geo" / "build_boundaries.py"
)
assert _BUILD_SPEC is not None and _BUILD_SPEC.loader is not None
build = importlib.util.module_from_spec(_BUILD_SPEC)
sys.modules["geo_build_boundaries"] = build
_BUILD_SPEC.loader.exec_module(build)
_SPEC = importlib.util.spec_from_file_location("geo_dissolve", ROOT / "geo" / "dissolve.py")
assert _SPEC is not None and _SPEC.loader is not None
dissolve = importlib.util.module_from_spec(_SPEC)
sys.modules["geo_dissolve"] = dissolve
_SPEC.loader.exec_module(dissolve)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_geo_build_preserves_hand_written_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = tmp_path / "docs"
    (docs / "adr").mkdir(parents=True)
    adr = docs / "adr" / "0002-geo-size-budget.md"
    adr.write_text("The approved hand-written decision.\n", encoding="utf-8")
    before = {
        path.relative_to(docs): path.read_bytes() for path in docs.rglob("*") if path.is_file()
    }

    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "OUT_DIR", tmp_path / "web" / "public" / "geo")
    monkeypatch.setattr(build, "ADR_PATH", adr, raising=False)
    monkeypatch.setattr(build, "_resolve_input", lambda codes: tmp_path / "input.geojson")
    monkeypatch.setattr(
        build, "_write_fsa_topojson", lambda src, codes, simplify, dest: dest.write_text("{}")
    )
    monkeypatch.setattr(build, "_gzip_size", lambda path: 2)

    assert build.main() == 0
    after = {
        path.relative_to(docs): path.read_bytes() for path in docs.rglob("*") if path.is_file()
    }
    assert after == before


def test_nearest_branch_wins_when_fsa_is_not_a_branch_site() -> None:
    sites = [
        dissolve.BranchSite("BR-0101", "M5H", (-79.38, 43.65), "GTA", "GTA", "ON", "Ontario"),
        dissolve.BranchSite(
            "BR-0201", "K1N", (-75.69, 45.43), "EON", "Eastern Ontario", "ON", "Ontario"
        ),
    ]
    # Closer to the Ottawa branch than to downtown Toronto.
    site = dissolve.nearest_site("K1Z", (-75.72, 45.40), sites)
    assert site.district_code == "EON"
    assert site.branch_id == "BR-0201"


def test_tie_prefers_the_branch_sited_in_the_fsa() -> None:
    point = (-79.38, 43.65)
    sites = [
        dissolve.BranchSite("BR-0199", "M5H", point, "GTA", "GTA", "ON", "Ontario"),
        dissolve.BranchSite(
            "BR-0101", "M6K", point, "SWO", "Southwestern Ontario", "ON", "Ontario"
        ),
    ]
    site = dissolve.nearest_site("M5H", point, sites)
    assert site.branch_id == "BR-0199"
    assert site.district_code == "GTA"


def test_thin_ring_over_one_square_kilometre_is_an_oversized_sliver() -> None:
    # ~0.15 km wide by ~20 km long at 45°N: compactness is tiny, area is over 1 km².
    ring = [
        (-79.40, 43.60),
        (-79.40, 43.78),
        (-79.398, 43.78),
        (-79.398, 43.60),
        (-79.40, 43.60),
    ]
    area, compactness, _ = dissolve.ring_area_compactness_centroid(ring)
    assert area > dissolve.SLIVER_AREA_KM2
    assert compactness < dissolve.SLIVER_COMPACTNESS_MAX
    assert dissolve.is_oversized_sliver(area, compactness)


def test_thin_ring_under_the_area_threshold_is_allowed() -> None:
    assert dissolve.is_oversized_sliver(0.2, 0.01) is False


def test_compact_polygon_is_not_a_sliver() -> None:
    assert dissolve.is_oversized_sliver(40.0, 0.6) is False


def test_branch_fsas_assign_to_org_districts() -> None:
    """Nearest branch of each shipped FSA matches the org.yaml district (dim_org codes)."""
    topo = _load(dissolve.FSA_PATH)
    rows = dissolve.build_lookup(topo, org())
    expected = {p.branch.fsa_code: p.district.district_code for p in org().placements()}
    assert {row.fsa_code: row.district_node_id for row in rows} == expected
    king = next(c for c in dissolve.fsa_centroids(topo).items() if c[0] == "M5H")
    lon, lat = king[1]
    assert -79.50 < lon < -79.30
    assert 43.64 < lat < 43.66


def test_district_and_region_ids_match_dim_org_codes() -> None:
    reference = org()
    districts = _load(dissolve.DISTRICTS_PATH)
    regions = _load(dissolve.REGIONS_PATH)
    district_geoms = dissolve.layer_geometries(districts, "districts")
    region_geoms = dissolve.layer_geometries(regions, "regions")
    assert len(district_geoms) == 14
    assert len(region_geoms) == 4

    district_ids = {g["properties"]["node_id"] for g in district_geoms}
    region_ids = {g["properties"]["node_id"] for g in region_geoms}
    assert district_ids == {d.district_code for d in reference.districts}
    assert region_ids == {r.value for r in RegionCode}

    district_names = {d.district_code: d.district_name for d in reference.districts}
    region_of = {d.district_code: reference.region_of(d.district_code) for d in reference.districts}
    for geom in district_geoms:
        props = geom["properties"]
        code = props["node_id"]
        assert props["node_name"] == district_names[code]
        assert props["parent_id"] == region_of[code].region_code.value
        assert geom["id"] == code

    region_names = {r.region_code.value: r.region_name for r in reference.regions}
    for geom in region_geoms:
        props = geom["properties"]
        code = props["node_id"]
        assert props["node_name"] == region_names[code]
        assert props["parent_id"] == reference.national.node_id
        assert geom["id"] == code


def test_no_slivers_larger_than_threshold() -> None:
    for path, layer in (
        (dissolve.DISTRICTS_PATH, "districts"),
        (dissolve.REGIONS_PATH, "regions"),
    ):
        found = dissolve.oversized_slivers(_load(path), layer)
        assert found == [], found


def test_combined_gzip_within_budget() -> None:
    size = dissolve.combined_gzip_bytes([dissolve.DISTRICTS_PATH, dissolve.REGIONS_PATH])
    assert size <= dissolve.MAX_COMBINED_GZIP_BYTES
