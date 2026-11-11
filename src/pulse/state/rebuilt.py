"""Which intermediate tables dbt rebuilds from scratch on every run, so persist may drop them.

An incremental model keeps state between runs: dropping its table would turn every weekly run
into a silent full refresh, and with a lookback-limited model the results could differ. So a
table is dropped only when every source that knows the model calls it a plain ``table``:

- this run's manifest (``$PULSE_DATA_DIR/dbt-target/manifest.json``), the configs dbt resolved;
- the model files themselves: ``dbt_project.yml``'s folder default, each model's ``.yml``
  config and its ``{{ config(...) }}`` block.

With neither source available nothing is dropped, which costs only a larger upload.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from pulse.warehouse import DBT_REBUILT_SCHEMA

DBT_DIR = Path(__file__).resolve().parents[3] / "dbt"
# runner.stages.DBT_TARGET_DIR: dbt build writes its target here, under the data dir.
MANIFEST = Path("dbt-target") / "manifest.json"
REBUILT = "table"

_CONFIG = re.compile(r"\{\{\s*config\s*\((.*?)\)\s*\}\}", re.DOTALL)
_MATERIALIZED = re.compile(r"materialized\s*=\s*['\"](\w+)['\"]")


def _from_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    nodes = json.loads(path.read_text(encoding="utf-8")).get("nodes", {})
    found: dict[str, str] = {}
    for node in nodes.values():
        config = node.get("config") or {}
        schema = config.get("schema") or node.get("schema")
        if node.get("resource_type") == "model" and schema == DBT_REBUILT_SCHEMA:
            found[node.get("alias") or node["name"]] = str(config.get("materialized"))
    return found


def _folder_default(dbt_dir: Path) -> str:
    project: dict[str, Any] = yaml.safe_load((dbt_dir / "dbt_project.yml").read_text()) or {}
    for package in (project.get("models") or {}).values():
        folder = (package or {}).get(DBT_REBUILT_SCHEMA) or {}
        value = folder.get("+materialized", folder.get("materialized"))
        if value:
            return str(value)
    return "view"  # dbt's own default


def _from_sources(dbt_dir: Path) -> dict[str, str]:
    folder = dbt_dir / "models" / DBT_REBUILT_SCHEMA
    if not (dbt_dir / "dbt_project.yml").exists() or not folder.is_dir():
        return {}
    default = _folder_default(dbt_dir)
    found = {sql.stem: default for sql in folder.glob("*.sql")}
    for spec in folder.glob("*.yml"):
        for model in (yaml.safe_load(spec.read_text()) or {}).get("models") or []:
            value = (model.get("config") or {}).get("materialized")
            if value and model.get("name") in found:
                found[model["name"]] = str(value)
    for sql in folder.glob("*.sql"):
        for block in _CONFIG.findall(sql.read_text(encoding="utf-8")):
            if match := _MATERIALIZED.search(block):
                found[sql.stem] = match.group(1)
    return found


def rebuilt_tables(data_dir: Path, dbt_dir: Path = DBT_DIR) -> frozenset[str]:
    """Intermediate tables that every known source says dbt rebuilds as a plain table."""
    sources = [s for s in (_from_manifest(data_dir / MANIFEST), _from_sources(dbt_dir)) if s]
    names = {name for source in sources for name in source}
    return frozenset(
        name for name in names if all(s.get(name, REBUILT) == REBUILT for s in sources)
    )
