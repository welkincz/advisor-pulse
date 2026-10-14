"""Download StatCan 2021 FSA boundaries, filter, simplify, emit TopoJSON for the web map.

Raw downloads stay under ``data/geo/`` (gitignored). Outputs land in ``web/public/geo/``.
Requires Node.js (``npx mapshaper``). Re-run via ``make geo``.

Source preference:
1. Cartographic shapefile zip (official package) when the CDN allows it.
2. Otherwise the same 2021 cartographic layer via Statistics Canada's public
   MapServer (Cloudflare often blocks unattended zip downloads).
"""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from pulse.reference import org

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "geo" / "cache"
RAW_DIR = ROOT / "data" / "geo" / "raw"
OUT_DIR = ROOT / "web" / "public" / "geo"
ADR_PATH = ROOT / "docs" / "adr" / "0002-geo-size-budget.md"

ZIP_NAME = "lfsa000b21a_e.zip"
DOWNLOAD_URL = (
    "https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/"
    "boundary-limites/files-fichiers/lfsa000b21a_e.zip"
)
MAPSERVER_QUERY = (
    "https://geo.statcan.gc.ca/geo_wa/rest/services/2021/"
    "Cartographic_boundary_files/MapServer/14/query"
)
SHP_STEM = "lfsa000b21a_e"
FSA_FIELD = "CFSAUID"
GEOJSON_CACHE = "fsa_branch_pool.geojson"

MAX_GZIP_BYTES = 3 * 1024 * 1024
# Mild → aggressive: keep the richest layer that still fits the gzip budget.
SIMPLIFY_STEPS = ("40%", "25%", "15%", "10%", "5%", "2%")
MAPSHAPER_PKG = "mapshaper@0.6.113"
USER_AGENT = "advisor-pulse-geo/0.1 (+https://github.com/welkincz/advisor-pulse)"
QUERY_BATCH = 15

ATTRIBUTION = """\
Adapted from Statistics Canada, Census Forward Sortation Area Boundary File, 2021.
This does not constitute an endorsement by Statistics Canada of this product.

Source product: lfsa000b21a_e / MapServer layer
"FSA - lfsa000b21s_e" (2021 cartographic boundary files).
Product index:
https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm?year=21

Licensed under the Statistics Canada Open Licence:
https://www.statcan.gc.ca/en/reference/licence

Advisor Pulse filters the national FSA layer to Maplecrest Bank (fictional) branch
FSAs from reference/org.yaml, reprojects to WGS84, and simplifies to TopoJSON for
the weekly report map. District/region polygons are derived in a follow-up issue.
"""


def _fsa_codes() -> list[str]:
    """Branch FSAs from org.yaml. Client-pool FSAs join when the generator (#13) lands."""
    return sorted({b.fsa_code for b in org().branches})


def _curl(url: str, *, data: bytes | None = None, timeout: int = 300) -> bytes:
    """HTTP via curl — more reliable TLS than urllib on some corporate macOS setups."""
    cmd = [
        "curl",
        "-fsSL",
        "-A",
        USER_AGENT,
        "--max-time",
        str(timeout),
    ]
    if data is not None:
        cmd.extend(["-X", "POST", "--data-binary", "@-"])
    cmd.append(url)
    try:
        return subprocess.check_output(cmd, input=data)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"curl failed for {url} (exit {exc.returncode})") from exc
    except FileNotFoundError:
        req = urllib.request.Request(
            url,
            data=data,
            headers={"User-Agent": USER_AGENT},
            method="POST" if data is not None else "GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()


def _http_get(url: str, *, timeout: int = 300) -> bytes:
    return _curl(url, timeout=timeout)


def _try_download_zip() -> Path | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = CACHE_DIR / ZIP_NAME
    if zip_path.is_file() and zip_path.stat().st_size > 0:
        print(f"cache hit: {zip_path}")
        return zip_path
    print(f"trying zip download {DOWNLOAD_URL}")
    tmp = zip_path.with_suffix(".zip.partial")
    try:
        data = _http_get(DOWNLOAD_URL)
    except RuntimeError as exc:
        # Cloudflare challenge HTML still "succeeds" for some clients; treat small/HTML as miss.
        print(f"zip download failed ({exc}); will use MapServer")
        return None
    if len(data) < 100_000 or data[:1] == b"<":
        print("zip download returned non-zip payload (likely CDN challenge); will use MapServer")
        return None
    tmp.write_bytes(data)
    tmp.replace(zip_path)
    print(f"cached {zip_path} ({zip_path.stat().st_size:,} bytes)")
    return zip_path


def _extract_shapefile(zip_path: Path) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    shp = RAW_DIR / f"{SHP_STEM}.shp"
    if not shp.is_file():
        print(f"extracting {zip_path.name} → {RAW_DIR}")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(RAW_DIR)
    matches = list(RAW_DIR.rglob(f"{SHP_STEM}.shp"))
    if not matches:
        raise FileNotFoundError(f"shapefile {SHP_STEM}.shp not found under {RAW_DIR}")
    return matches[0]


def _query_mapserver_batch(codes: list[str]) -> list[dict[str, Any]]:
    quoted = ",".join(f"'{c}'" for c in codes)
    where = f"{FSA_FIELD} IN ({quoted})"
    body = urllib.parse.urlencode(
        {
            "where": where,
            "outFields": FSA_FIELD,
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        }
    ).encode("utf-8")
    # POST avoids URL-length limits on large IN (...) lists.
    raw = _curl(MAPSERVER_QUERY, data=body, timeout=180)
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(f"MapServer error: {payload['error']}")
    features = payload.get("features")
    if not isinstance(features, list):
        raise RuntimeError("MapServer response missing features[]")
    return features


def _fetch_geojson_via_mapserver(codes: list[str]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / GEOJSON_CACHE
    if dest.is_file() and dest.stat().st_size > 0:
        # Rebuild if the org FSA set drifted (count or membership).
        existing = json.loads(dest.read_text(encoding="utf-8"))
        have = {str(f.get("properties", {}).get(FSA_FIELD)) for f in existing.get("features", [])}
        if have == set(codes):
            print(f"cache hit: {dest} ({len(have)} FSAs)")
            return dest

    print(f"fetching {len(codes)} FSAs from StatCan MapServer (batched)")
    features: list[dict[str, Any]] = []
    for i in range(0, len(codes), QUERY_BATCH):
        batch = codes[i : i + QUERY_BATCH]
        print(f"  batch {i // QUERY_BATCH + 1}: {len(batch)} codes")
        features.extend(_query_mapserver_batch(batch))

    got = {str(f.get("properties", {}).get(FSA_FIELD)) for f in features}
    missing = sorted(set(codes) - got)
    if missing:
        sample = ", ".join(missing[:20])
        more = "…" if len(missing) > 20 else ""
        raise RuntimeError(f"MapServer missing FSAs: {sample}{more}")

    collection = {"type": "FeatureCollection", "features": features}
    dest.write_text(json.dumps(collection), encoding="utf-8")
    print(f"cached {dest} ({dest.stat().st_size:,} bytes)")
    return dest


def _resolve_input(codes: list[str]) -> Path:
    zip_path = _try_download_zip()
    if zip_path is not None:
        return _extract_shapefile(zip_path)
    return _fetch_geojson_via_mapserver(codes)


def _mapshaper(*args: str) -> None:
    cmd = ["npx", "--yes", MAPSHAPER_PKG, *args]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def _gzip_size(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), compresslevel=9))


def _filter_expression(codes: list[str]) -> str:
    lit = json.dumps(codes)
    return f"{lit}.includes({FSA_FIELD})"


def _write_fsa_topojson(src: Path, codes: list[str], simplify: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pulse-geo-") as tmp:
        out = Path(tmp) / "fsa.topo.json"
        args = [str(src), "-proj", "wgs84"]
        # MapServer geojson is already filtered; shapefile path still needs -filter.
        if src.suffix.lower() == ".shp":
            args.extend(["-filter", _filter_expression(codes)])
        args.extend(
            [
                "-simplify",
                "dp",
                simplify,
                "keep-shapes",
                "-filter-fields",
                FSA_FIELD,
                "-rename-layers",
                "fsa",
                "-o",
                "format=topojson",
                "precision=0.0001",
                str(out),
            ]
        )
        _mapshaper(*args)
        shutil.copyfile(out, dest)


def _write_district_fallback(src: Path, codes: list[str], dest: Path) -> tuple[int, str]:
    """Dissolve branch FSAs to district polygons when FSA layer exceeds the budget."""
    by_fsa = {p.branch.fsa_code: p.district.district_code for p in org().placements()}
    with tempfile.TemporaryDirectory(prefix="pulse-geo-dist-") as tmp:
        tmp_path = Path(tmp)
        lookup = tmp_path / "fsa_district.csv"
        lookup.write_text(
            "fsa_code,district_code\n"
            + "\n".join(f"{f},{d}" for f, d in sorted(by_fsa.items()))
            + "\n",
            encoding="utf-8",
        )
        dissolved = tmp_path / "districts.topo.json"
        args = [str(src), "-proj", "wgs84"]
        if src.suffix.lower() == ".shp":
            args.extend(["-filter", _filter_expression(codes)])
        args.extend(
            [
                "-join",
                str(lookup),
                f"keys={FSA_FIELD},fsa_code",
                "-dissolve",
                "district_code",
                "copy-fields=district_code",
                "-simplify",
                "dp",
                "10%",
                "keep-shapes",
                "-o",
                "format=topojson",
                "precision=0.0001",
                str(dissolved),
            ]
        )
        _mapshaper(*args)
        shutil.copyfile(dissolved, dest)
    return _gzip_size(dest), "district"


def _write_adr(*, level: str, gzip_bytes: int, simplify: str | None, fsa_count: int) -> None:
    ADR_PATH.parent.mkdir(parents=True, exist_ok=True)
    mb = gzip_bytes / (1024 * 1024)
    if level == "fsa":
        decision = (
            f"Ship **FSA-level** TopoJSON (`web/public/geo/fsa.topo.json`). "
            f"Gzip size is **{mb:.2f} MB** (budget ≤ 3.00 MB) at mapshaper "
            f"Douglas-Peucker simplify `{simplify}` keep-shapes, {fsa_count} FSAs "
            f"from `reference/org.yaml`."
        )
        status = "Accepted — FSA layer within budget"
    else:
        decision = (
            f"FSA-level TopoJSON exceeded the **3 MB gzip** budget at every "
            f"tried simplify step ({', '.join(SIMPLIFY_STEPS)}). "
            f"Fall back to **district-level** polygons "
            f"(`web/public/geo/district.topo.json`), gzip **{mb:.2f} MB**, "
            f"dissolved from the same {fsa_count} branch FSAs."
        )
        status = "Accepted — district fallback"
    ADR_PATH.write_text(
        f"""# ADR 0002 — Geo size budget (FSA vs district)

- Status: {status}
- Date: 2026-10-14
- Issue: #31

## Context

The weekly report map may show StatCan FSA boundaries (optional layer). PLAN.md
caps the shipped geo payload at **3 MB gzip**. If FSA fidelity cannot stay under
that budget, ship only district (and later region) polygons.

## Decision

{decision}

Client-pool FSAs from the synthetic generator (#13) are not in the filter set yet;
re-run `make geo` when that pool exists so neighbouring FSAs used by clients are
included.

`make geo` prefers the official `lfsa000b21a_e.zip` package (cached under
`data/geo/cache/`). If the CDN blocks automated downloads, it falls back to the
same 2021 cartographic FSA layer on Statistics Canada's public MapServer and
caches the filtered GeoJSON under `data/geo/cache/` — still not committed.

## Consequences

- `manifest.json` `has_fsa_boundaries` is true only when `fsa.topo.json` is shipped.
- Issue #32 derives district/region dissolves from the FSA layer when FSA ships;
  if this ADR chose district fallback, #32 should start from `district.topo.json`
  or re-evaluate the budget after further simplification.
- Raw StatCan downloads remain under `data/geo/` and are never committed.
""",
        encoding="utf-8",
    )


def main() -> int:
    codes = _fsa_codes()
    print(f"target FSAs: {len(codes)} (from reference/org.yaml)")
    src = _resolve_input(codes)
    print(f"input: {src}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "ATTRIBUTION.txt").write_text(ATTRIBUTION, encoding="utf-8")

    fsa_out = OUT_DIR / "fsa.topo.json"
    district_out = OUT_DIR / "district.topo.json"
    for stale in (fsa_out, district_out):
        if stale.exists():
            stale.unlink()

    chosen_simplify: str | None = None
    gzip_bytes = 0
    level = "fsa"

    for simplify in SIMPLIFY_STEPS:
        print(f"trying FSA simplify={simplify}")
        _write_fsa_topojson(src, codes, simplify, fsa_out)
        gzip_bytes = _gzip_size(fsa_out)
        raw_bytes = fsa_out.stat().st_size
        print(
            f"  raw={raw_bytes:,} bytes  gzip={gzip_bytes:,} bytes "
            f"({gzip_bytes / (1024 * 1024):.2f} MB)"
        )
        if gzip_bytes <= MAX_GZIP_BYTES:
            chosen_simplify = simplify
            break
    else:
        print("FSA layer over budget at all simplify steps; dissolving to district")
        if fsa_out.exists():
            fsa_out.unlink()
        gzip_bytes, level = _write_district_fallback(src, codes, district_out)
        print(f"district gzip={gzip_bytes:,} bytes ({gzip_bytes / (1024 * 1024):.2f} MB)")

    _write_adr(
        level=level,
        gzip_bytes=gzip_bytes,
        simplify=chosen_simplify,
        fsa_count=len(codes),
    )
    print(f"wrote attribution → {OUT_DIR / 'ATTRIBUTION.txt'}")
    print(f"wrote ADR → {ADR_PATH}")
    shipped = fsa_out if level == "fsa" else district_out
    print(f"shipped {level} layer → {shipped} (gzip {gzip_bytes:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
