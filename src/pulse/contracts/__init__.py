"""Data contracts: one pydantic model per table or document in PLAN.md §6.

Every producer and consumer (generator, ingestion, dbt, export, web types) derives its
schema from these models. ``REGISTRY`` maps each contract name to its model.
"""

from __future__ import annotations

from pulse.contracts.base import (
    SCHEMA_VERSION,
    Column,
    Contract,
    arrow_schema,
    column_names,
    columns,
    duckdb_columns,
)
from pulse.contracts.exports import EXPORT_DOCUMENT_CONTRACTS, EXPORT_TABLE_CONTRACTS
from pulse.contracts.meta import META_CONTRACTS
from pulse.contracts.raw import RAW_CONTRACTS, RawMetadata
from pulse.contracts.sources import SOURCE_CONTRACTS

ALL_CONTRACTS: tuple[type[Contract], ...] = (
    *SOURCE_CONTRACTS,
    RawMetadata,
    *RAW_CONTRACTS,
    *META_CONTRACTS,
    *EXPORT_TABLE_CONTRACTS,
    *EXPORT_DOCUMENT_CONTRACTS,
)

REGISTRY: dict[str, type[Contract]] = {m.contract_name: m for m in ALL_CONTRACTS}

if len(REGISTRY) != len(ALL_CONTRACTS):
    raise RuntimeError("Duplicate contract_name in pulse.contracts")

__all__ = [
    "ALL_CONTRACTS",
    "REGISTRY",
    "SCHEMA_VERSION",
    "Column",
    "Contract",
    "arrow_schema",
    "column_names",
    "columns",
    "duckdb_columns",
]
