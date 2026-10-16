"""Write ``dbt/models/sources.yml`` from the warehouse table contracts.

python -m pulse.dbt_sources          # write
python -m pulse.dbt_sources --check  # exit 1 if the committed file is stale

dbt sees the same tables, columns and types that ingestion creates, so a contract change
cannot silently leave dbt behind (``make contracts-check`` runs the check).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from pulse.contracts import columns, duckdb_columns
from pulse.warehouse import TABLES

ROOT = Path(__file__).resolve().parents[2]
DBT_SOURCES = ROOT / "dbt" / "models" / "sources.yml"

# Raw tables are loaded weekly; a source older than this has missed a run (PLAN.md §8).
RAW_FRESHNESS = {
    "warn_after": {"count": 8, "period": "day"},
    "error_after": {"count": 15, "period": "day"},
}
SCHEMA_DESCRIPTIONS = {
    "raw": "Source rows as loaded by ingestion: one row per loaded source row, duplicates "
    "kept, plus _batch_id/_source_file/_source_row/_row_hash/_loaded_at.",
    "meta": "Pipeline state: watermarks, the file manifest, run log and check results.",
    "quarantine": "Rows rejected at ingest by rules DQ001–DQ005, with rule and payload.",
}
HEADER = "# Generated from src/pulse/contracts by `make contracts`. Do not edit by hand.\n"


def render() -> str:
    """dbt ``sources.yml`` for every table in :data:`pulse.warehouse.TABLES`."""
    by_schema: dict[str, list[dict[str, Any]]] = {}
    for spec in TABLES:
        schema, table = spec.name.split(".", 1)
        types = {name: sql_type for name, sql_type, _ in duckdb_columns(spec.model)}
        entry: dict[str, Any] = {
            "name": table,
            "description": spec.model.contract_description or f"Contract {spec.model.__name__}.",
        }
        if schema == "raw":
            entry["loaded_at_field"] = "_loaded_at"
            entry["freshness"] = RAW_FRESHNESS
        entry["columns"] = [
            {"name": c.name, "data_type": types[c.name]}
            | ({"description": c.description} if c.description else {})
            for c in columns(spec.model)
        ]
        by_schema.setdefault(schema, []).append(entry)
    document = {
        "version": 2,
        "sources": [
            {"name": schema, "schema": schema, "description": SCHEMA_DESCRIPTIONS[schema]}
            | {"tables": tables}
            for schema, tables in by_schema.items()
        ],
    }
    return HEADER + yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--check", action="store_true", help="Fail if the file is stale.")
    args = parser.parse_args(argv)
    name = DBT_SOURCES.relative_to(ROOT)
    if args.check:
        if not DBT_SOURCES.exists() or DBT_SOURCES.read_text(encoding="utf-8") != render():
            print(f"{name} is stale (run `make contracts`).", file=sys.stderr)
            return 1
        print(f"{name} is up to date ({len(TABLES)} tables).")
        return 0
    DBT_SOURCES.parent.mkdir(parents=True, exist_ok=True)
    DBT_SOURCES.write_text(render(), encoding="utf-8")
    print(f"Wrote {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
