"""Download Natural Earth admin-1 boundaries and emit the Canadian province basemap.

The FSA layer only covers branch FSAs, so on its own the map is a few specks on blank
paper. This layer draws every province and territory, tagged with its Maplecrest region
(regions follow the provinces; territories have none), so the map reads as Canada at a glance.

Natural Earth is public domain. Raw downloads stay under ``data/geo/`` (gitignored);
the output lands in ``web/public/geo/provinces.topo.json``. Requires Node.js (``npx
mapshaper``). Run with ``uv run python geo/build_provinces.py``.
"""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from pulse.reference import org

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "geo" / "cache"
OUT = ROOT / "web" / "public" / "geo" / "provinces.topo.json"

NE_VERSION = "v5.1.2"
NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    f"{NE_VERSION}/geojson/ne_50m_admin_1_states_provinces.geojson"
)
MAPSHAPER_PKG = "mapshaper@0.6.113"
SIMPLIFY = "30%"
MAX_GZIP_BYTES = 80 * 1024


def province_regions() -> dict[str, str]:
    """Province code -> region code, from the districts in reference/org.yaml."""
    return {
        province: region.region_code
        for region in org().regions
        for district in region.districts
        for province in district.provinces
    }


def canada_features(collection: dict[str, Any]) -> list[dict[str, Any]]:
    """Canadian provinces and territories with only the fields the web map reads."""
    regions = province_regions()
    features: list[dict[str, Any]] = []
    for feature in collection["features"]:
        props = feature["properties"]
        if props.get("adm0_a3") != "CAN":
            continue
        code = props["postal"]
        features.append(
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": {
                    "province": code,
                    "name": props["name"],
                    "region_code": regions.get(code),
                },
            }
        )
    return sorted(features, key=lambda f: str(f["properties"]["province"]))


def _download() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"ne_50m_admin_1_{NE_VERSION}.geojson"
    if not path.exists():
        subprocess.run(["curl", "-fsSL", "-o", str(path), NE_URL], check=True)
    return path


def main() -> int:
    source = json.loads(_download().read_text(encoding="utf-8"))
    features = canada_features(source)
    if len(features) != 13:
        print(f"Expected 13 provinces and territories, found {len(features)}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="pulse-geo-") as tmp:
        src = Path(tmp) / "canada.geojson"
        src.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
        out = Path(tmp) / "provinces.topo.json"
        cmd = [
            "npx", "--yes", MAPSHAPER_PKG, str(src),
            "-simplify", "visvalingam", "weighted", SIMPLIFY, "keep-shapes",
            "-filter-islands", "min-area=400km2",
            "-rename-layers", "provinces",
            "-o", "format=topojson", "quantization=20000", str(out),
        ]  # fmt: skip
        subprocess.run(cmd, check=True, cwd=ROOT)
        size = len(gzip.compress(out.read_bytes(), compresslevel=9))
        if size > MAX_GZIP_BYTES:
            budget = f"provinces.topo.json is {size} bytes gzip; budget {MAX_GZIP_BYTES}"
            print(budget, file=sys.stderr)
            return 1
        OUT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, OUT)
    print(f"Wrote {OUT.relative_to(ROOT)}: {OUT.stat().st_size} bytes, {size} gzip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
