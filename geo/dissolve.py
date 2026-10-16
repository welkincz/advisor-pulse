"""Dissolve branch FSA polygons into district and region TopoJSON.

Each FSA in ``web/public/geo/fsa.topo.json`` is assigned to the district of its
nearest Maplecrest branch (issue #32). Branch FSAs sit on the branch, so the
nearest site is that branch and the district matches ``reference/org.yaml``
(the codes ``dim_org`` uses). Features carry ``node_id`` from the marts:
district code, or region code, with ``parent_id`` of the region or ``CA``.

Slivers are rings thinner than ``SLIVER_COMPACTNESS_MAX`` (Polsby-Popper).
None may be larger than ``SLIVER_AREA_KM2``. Mapshaper ``-clean`` fills gaps
up to that area. Combined gzip of the two outputs must stay ≤ 500 KB.
"""

from __future__ import annotations

import csv
import gzip
import itertools
import json
import math
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pulse.reference import OrgReference, org

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "web" / "public" / "geo"
FSA_PATH = OUT_DIR / "fsa.topo.json"
DISTRICTS_PATH = OUT_DIR / "districts.topo.json"
REGIONS_PATH = OUT_DIR / "regions.topo.json"

FSA_FIELD = "CFSAUID"
MAPSHAPER_PKG = "mapshaper@0.6.113"
MAX_COMBINED_GZIP_BYTES = 500 * 1024
# Below this, a ring is thin enough to treat as a topology sliver, not an FSA or a lake.
SLIVER_COMPACTNESS_MAX = 0.05
# Acceptance: no sliver larger than this (km²).
SLIVER_AREA_KM2 = 1.0
GAP_FILL_AREA = "1km2"
EARTH_KM = 6371.0088


@dataclass(frozen=True)
class BranchSite:
    branch_id: str
    fsa_code: str
    point: tuple[float, float]
    district_code: str
    district_name: str
    region_code: str
    region_name: str


@dataclass(frozen=True)
class LookupRow:
    fsa_code: str
    district_node_id: str
    district_node_name: str
    district_parent_id: str
    region_node_id: str
    region_node_name: str
    region_parent_id: str


@dataclass(frozen=True)
class RingMeasure:
    node_id: str
    kind: str
    area_km2: float
    compactness: float


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = a
    lon2, lat2 = b
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


def nearest_site(
    fsa_code: str, point: tuple[float, float], sites: tuple[BranchSite, ...] | list[BranchSite]
) -> BranchSite:
    """District of the nearest branch. Ties break toward the branch sited in this FSA."""

    def key(site: BranchSite) -> tuple[float, int, str]:
        same_fsa = 0 if site.fsa_code == fsa_code else 1
        return (haversine_km(point, site.point), same_fsa, site.branch_id)

    return min(sites, key=key)


def decode_lines(topo: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Delta-decode TopoJSON arcs to lon/lat lines. Quantization is optional."""
    transform = topo.get("transform")
    if transform:
        sx, sy = transform["scale"]
        tx, ty = transform["translate"]
    else:
        sx = sy = 1.0
        tx = ty = 0.0
    lines: list[list[tuple[float, float]]] = []
    for arc in topo["arcs"]:
        x = y = 0.0
        coords: list[tuple[float, float]] = []
        for dx, dy in arc:
            x += dx
            y += dy
            coords.append((x * sx + tx, y * sy + ty))
        lines.append(coords)
    return lines


def stitch_ring(
    lines: list[list[tuple[float, float]]], indexes: list[int]
) -> list[tuple[float, float]]:
    ring: list[tuple[float, float]] = []
    for idx in indexes:
        arc = lines[idx] if idx >= 0 else lines[~idx][::-1]
        ring.extend(arc if not ring else arc[1:])
    return ring


def _polygons(geom: dict[str, Any]) -> list[list[list[int]]]:
    kind = geom["type"]
    arcs = geom["arcs"]
    if kind == "Polygon":
        return [arcs]
    if kind == "MultiPolygon":
        return list(arcs)
    raise ValueError(f"unsupported geometry {kind}")


def ring_area_compactness_centroid(
    ring: list[tuple[float, float]],
) -> tuple[float, float, tuple[float, float]]:
    """Equirectangular area (km²), Polsby-Popper compactness, and area-weighted centroid."""
    if len(ring) < 4:
        n = max(len(ring), 1)
        lon = sum(p[0] for p in ring) / n
        lat = sum(p[1] for p in ring) / n
        return 0.0, 0.0, (lon, lat)
    lat0 = sum(p[1] for p in ring) / len(ring)
    mx = 111.32 * math.cos(math.radians(lat0))
    my = 111.32
    area2 = 0.0
    peri = 0.0
    cx = cy = 0.0
    for (x1, y1), (x2, y2) in itertools.pairwise(ring):
        cross = x1 * y2 - x2 * y1
        area2 += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
        peri += math.hypot((x2 - x1) * mx, (y2 - y1) * my)
    area_deg = area2 / 2
    area_km2 = abs(area_deg) * mx * my
    compactness = (4 * math.pi * area_km2 / (peri * peri)) if peri else 0.0
    if abs(area_deg) < 1e-18:
        n = len(ring)
        centroid = (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)
    else:
        centroid = (cx / (6 * area_deg), cy / (6 * area_deg))
    return area_km2, compactness, centroid


def is_oversized_sliver(area_km2: float, compactness: float) -> bool:
    return compactness < SLIVER_COMPACTNESS_MAX and area_km2 > SLIVER_AREA_KM2


def fsa_centroids(topo: dict[str, Any]) -> dict[str, tuple[float, float]]:
    lines = decode_lines(topo)
    layer = topo["objects"]["fsa"]
    out: dict[str, tuple[float, float]] = {}
    for geom in layer["geometries"]:
        code = str(geom["properties"][FSA_FIELD])
        best_area = -1.0
        best: tuple[float, float] | None = None
        for poly in _polygons(geom):
            exterior = stitch_ring(lines, poly[0])
            area, _, centroid = ring_area_compactness_centroid(exterior)
            if area > best_area:
                best_area = area
                best = centroid
        if best is None:
            raise RuntimeError(f"FSA {code} has no exterior ring")
        out[code] = best
    return out


def branch_sites(
    reference: OrgReference, centroids: dict[str, tuple[float, float]]
) -> tuple[BranchSite, ...]:
    missing = [
        p.branch.fsa_code for p in reference.placements() if p.branch.fsa_code not in centroids
    ]
    if missing:
        sample = ", ".join(missing[:12])
        raise RuntimeError(f"FSA layer is missing branch FSAs: {sample}")
    return tuple(
        BranchSite(
            branch_id=p.branch.branch_id,
            fsa_code=p.branch.fsa_code,
            point=centroids[p.branch.fsa_code],
            district_code=p.district.district_code,
            district_name=p.district.district_name,
            region_code=p.region.region_code.value,
            region_name=p.region.region_name,
        )
        for p in reference.placements()
    )


def build_lookup(topo: dict[str, Any], reference: OrgReference) -> list[LookupRow]:
    """Assign every FSA to the district of its nearest branch."""
    centroids = fsa_centroids(topo)
    sites = branch_sites(reference, centroids)
    by_fsa = {s.fsa_code: s for s in sites}
    rows: list[LookupRow] = []
    for fsa_code, point in sorted(centroids.items()):
        site = nearest_site(fsa_code, point, sites)
        owner = by_fsa.get(fsa_code)
        if owner is not None and site.district_code != owner.district_code:
            raise RuntimeError(
                f"{fsa_code} nearest branch {site.branch_id} is in {site.district_code}, "
                f"not org.yaml district {owner.district_code}"
            )
        rows.append(
            LookupRow(
                fsa_code=fsa_code,
                district_node_id=site.district_code,
                district_node_name=site.district_name,
                district_parent_id=site.region_code,
                region_node_id=site.region_code,
                region_node_name=site.region_name,
                region_parent_id=reference.national.node_id,
            )
        )
    return rows


def layer_geometries(topo: dict[str, Any], name: str) -> list[dict[str, Any]]:
    objects = topo["objects"]
    if name not in objects:
        raise KeyError(f"TopoJSON missing layer {name!r}; has {sorted(objects)}")
    return list(objects[name]["geometries"])


def oversized_slivers(topo: dict[str, Any], layer_name: str) -> list[RingMeasure]:
    lines = decode_lines(topo)
    found: list[RingMeasure] = []
    for geom in layer_geometries(topo, layer_name):
        node_id = str(geom.get("properties", {}).get("node_id") or geom.get("id") or "")
        for poly in _polygons(geom):
            for kind, indexes in _ring_kinds(poly):
                area, compactness, _ = ring_area_compactness_centroid(stitch_ring(lines, indexes))
                if is_oversized_sliver(area, compactness):
                    found.append(RingMeasure(node_id, kind, area, compactness))
    return found


def _ring_kinds(poly: list[list[int]]) -> list[tuple[str, list[int]]]:
    kinds = [("exterior", poly[0])]
    kinds.extend(("hole", ring) for ring in poly[1:])
    return kinds


def combined_gzip_bytes(paths: list[Path]) -> int:
    return sum(len(gzip.compress(path.read_bytes(), compresslevel=9)) for path in paths)


def _write_lookup(path: Path, rows: list[LookupRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(LookupRow.__dataclass_fields__))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def _mapshaper(args: list[str]) -> None:
    cmd = ["npx", "--yes", MAPSHAPER_PKG, *args]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def _dissolve_one(
    src: Path,
    lookup: Path,
    dest: Path,
    *,
    dissolve_field: str,
    copy_fields: str,
    rename: str,
    layer_name: str,
) -> None:
    _mapshaper(
        [
            str(src),
            "-join",
            str(lookup),
            f"keys={FSA_FIELD},fsa_code",
            "-dissolve",
            dissolve_field,
            f"copy-fields={copy_fields}",
            "-rename-fields",
            rename,
            "-filter-fields",
            "node_id,node_name,parent_id",
            "-rename-layers",
            layer_name,
            "-clean",
            f"gap-fill-area={GAP_FILL_AREA}",
            "-o",
            "format=topojson",
            "id-field=node_id",
            str(dest),
        ]
    )


def _build(src: Path, lookup: Path, dest_dir: Path) -> None:
    _dissolve_one(
        src,
        lookup,
        dest_dir / "districts.topo.json",
        dissolve_field="district_node_id",
        copy_fields="district_node_id,district_node_name,district_parent_id",
        rename="node_id=district_node_id,node_name=district_node_name,parent_id=district_parent_id",
        layer_name="districts",
    )
    _dissolve_one(
        src,
        lookup,
        dest_dir / "regions.topo.json",
        dissolve_field="region_node_id",
        copy_fields="region_node_id,region_node_name,region_parent_id",
        rename="node_id=region_node_id,node_name=region_node_name,parent_id=region_parent_id",
        layer_name="regions",
    )


def _assert_clean(districts: Path, regions: Path) -> int:
    problems: list[str] = []
    for path, layer in ((districts, "districts"), (regions, "regions")):
        topo = json.loads(path.read_text(encoding="utf-8"))
        for sliver in oversized_slivers(topo, layer):
            problems.append(
                f"{layer} {sliver.node_id} {sliver.kind}: "
                f"{sliver.area_km2:.3f} km² compactness {sliver.compactness:.3f}"
            )
    if problems:
        detail = "\n".join(problems)
        raise RuntimeError(f"slivers over {SLIVER_AREA_KM2:g} km²:\n{detail}")
    size = combined_gzip_bytes([districts, regions])
    print(f"combined gzip={size:,} bytes (budget {MAX_COMBINED_GZIP_BYTES:,})")
    return size


def main() -> int:
    if not FSA_PATH.is_file():
        raise SystemExit(f"missing {FSA_PATH}; run the FSA boundary step first (issue #31)")
    reference = org()
    topo = json.loads(FSA_PATH.read_text(encoding="utf-8"))
    rows = build_lookup(topo, reference)
    print(f"assigned {len(rows)} FSAs to {len({r.district_node_id for r in rows})} districts")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pulse-dissolve-") as tmp:
        tmp_path = Path(tmp)
        lookup = tmp_path / "fsa_org.csv"
        _write_lookup(lookup, rows)
        _build(FSA_PATH, lookup, tmp_path)
        districts = tmp_path / "districts.topo.json"
        regions = tmp_path / "regions.topo.json"
        size = _assert_clean(districts, regions)
        if size > MAX_COMBINED_GZIP_BYTES:
            raise RuntimeError(
                f"district + region TopoJSON is {size:,} bytes gzip; "
                f"budget is {MAX_COMBINED_GZIP_BYTES:,}"
            )
        shutil.copyfile(districts, DISTRICTS_PATH)
        shutil.copyfile(regions, REGIONS_PATH)
    print(f"wrote {DISTRICTS_PATH}")
    print(f"wrote {REGIONS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
