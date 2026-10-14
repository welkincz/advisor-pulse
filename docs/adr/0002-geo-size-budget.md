# ADR 0002 — Geo size budget (FSA vs district)

- Status: Accepted — FSA layer within budget
- Date: 2026-10-14
- Issue: #31

## Context

The weekly report map may show StatCan FSA boundaries (optional layer). PLAN.md
caps the shipped geo payload at **3 MB gzip**. If FSA fidelity cannot stay under
that budget, ship only district (and later region) polygons.

## Decision

Ship **FSA-level** TopoJSON (`web/public/geo/fsa.topo.json`). Gzip size is **0.11 MB** (budget ≤ 3.00 MB) at mapshaper Douglas-Peucker simplify `40%` keep-shapes, 122 FSAs from `reference/org.yaml`.

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
