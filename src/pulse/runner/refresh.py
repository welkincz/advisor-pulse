"""Which incremental dbt tables need a full refresh before this run's build (#304).

An incremental model keeps the history it built. If its definition changes, the weeks
before its rebuild floor keep the old logic, so a weekly run would mix two definitions.
Each incremental table therefore carries a stamp (a DuckDB table comment, kept by persist
and restore with the table itself):

- ``fingerprint``: a hash of the model's definition and of everything it is built from:
  the SQL, config and declared columns of the model and of every model and seed upstream,
  the project macros they use (and the incremental strategy's macro), and
  ``dbt_project.yml``. Descriptions are left out, so a docs edit refreshes nothing.
- ``loaded_through``: the newest raw ``_loaded_at`` when the build began. The models'
  rebuild floor reaches back to the earliest week of any row loaded after it
  (``dbt/macros/weekly_incremental.sql``).

Before the build, a table whose stamp is missing or names another fingerprint is dropped,
so dbt builds it in full; anything downstream that reads it has that model upstream and so
a changed fingerprint too. After the build, each incremental model that succeeded is
stamped again.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

PACKAGE = "advisor_pulse"
STAMP_KEY = "pulse_fingerprint"
# Raw tables whose new rows the rebuild floor looks at (weekly_incremental.sql).
WATERMARK_TABLES = (
    "raw.snowflake__activity",
    "raw.teradata__clnt",
    "raw.teradata__advsr_asgn",
    "raw.teradata__prtf_asgn",
)


@dataclass(frozen=True)
class Incremental:
    unique_id: str
    schema: str
    name: str
    fingerprint: str


def _ancestors(nodes: Mapping[str, Any], start: str) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        for parent in nodes[stack.pop()].get("depends_on", {}).get("nodes", []):
            if parent in nodes and parent not in seen:  # sources are not nodes here
                seen.add(parent)
                stack.append(parent)
    return seen


def _macros(macros: Mapping[str, Any], start: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    stack = [m for m in start if m in macros]
    while stack:
        macro = stack.pop()
        if macro in seen or macros[macro]["package_name"] != PACKAGE:
            continue
        seen.add(macro)
        stack.extend(
            m for m in macros[macro].get("depends_on", {}).get("macros", []) if m in macros
        )
    return seen


def _node_part(node: Mapping[str, Any]) -> list[Any]:
    columns = sorted(
        (name, column.get("data_type"), json.dumps(column.get("constraints", []), sort_keys=True))
        for name, column in (node.get("columns") or {}).items()
    )
    return [node["unique_id"], node["checksum"]["checksum"], node.get("config"), columns]


def incremental_models(manifest: Mapping[str, Any], project_file: Path) -> list[Incremental]:
    """Every incremental model in the manifest, with its definition fingerprint."""
    nodes, macros = manifest["nodes"], manifest["macros"]
    project = hashlib.sha256(project_file.read_bytes()).hexdigest()
    found = []
    for uid, node in sorted(nodes.items()):
        config = node.get("config") or {}
        if node["resource_type"] != "model" or config.get("materialized") != "incremental":
            continue
        members = sorted({uid} | _ancestors(nodes, uid))
        used = {
            m for member in members for m in nodes[member].get("depends_on", {}).get("macros", [])
        }
        if strategy := config.get("incremental_strategy"):
            used.add(f"macro.{PACKAGE}.get_incremental_{strategy}_sql")
        payload = {
            "project": project,
            "nodes": [_node_part(nodes[member]) for member in members],
            "macros": sorted((m, macros[m]["macro_sql"]) for m in _macros(macros, used)),
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode())
        found.append(
            Incremental(uid, node["schema"], node.get("alias") or node["name"], digest.hexdigest())
        )
    return found


def read_stamps(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, str], str | None]:
    """Fingerprint stamped on each existing table (None when it has no stamp)."""
    stamps: dict[tuple[str, str], str | None] = {}
    for schema, table, comment in con.execute(
        "select schema_name, table_name, comment from duckdb_tables()"
        " where database_name = current_database()"
    ).fetchall():
        try:
            stamp = json.loads(comment) if comment else {}
        except json.JSONDecodeError:
            stamp = {}
        stamps[(schema, table)] = stamp.get(STAMP_KEY) if isinstance(stamp, dict) else None
    return stamps


def stale(con: duckdb.DuckDBPyConnection, models: Iterable[Incremental]) -> list[Incremental]:
    """Existing tables built from another definition, or never stamped. A table that does
    not exist is left out: dbt builds it in full anyway."""
    stamps = read_stamps(con)
    return [
        m
        for m in models
        if (m.schema, m.name) in stamps and stamps[(m.schema, m.name)] != m.fingerprint
    ]


def drop(con: duckdb.DuckDBPyConnection, models: Iterable[Incremental]) -> None:
    for m in models:
        con.execute(f'drop table if exists "{m.schema}"."{m.name}"')


def loaded_through(con: duckdb.DuckDBPyConnection) -> str | None:
    """The newest raw load time, as an ISO timestamp, or None before any load."""
    parts = " union all ".join(
        f"select max(_loaded_at) as loaded from {t}" for t in WATERMARK_TABLES
    )
    row = con.execute(f"select max(loaded) from ({parts})").fetchone()
    return row[0].isoformat() if row and row[0] is not None else None


def stamp(
    con: duckdb.DuckDBPyConnection, models: Iterable[Incremental], through: str | None
) -> None:
    """Record each model's fingerprint and the load it saw on its table."""
    existing = read_stamps(con)
    for m in models:
        if (m.schema, m.name) not in existing:
            continue
        comment = json.dumps({STAMP_KEY: m.fingerprint, "loaded_through": through})
        con.execute(f'comment on table "{m.schema}"."{m.name}" is \'{comment}\'')
