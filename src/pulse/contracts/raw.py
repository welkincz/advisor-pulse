"""Raw-layer contracts (PLAN.md §6.4): source columns as-is plus load metadata."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from pulse.contracts.base import Contract
from pulse.contracts.sources import (
    SnowflakeActivity,
    TeradataAdvisor,
    TeradataAssignment,
    TeradataBranch,
    TeradataClient,
)


class RawMetadata(Contract):
    contract_name = "raw_metadata"
    contract_description = "Columns appended to every raw table by ingestion."

    batch_id: str = Field(
        alias="_batch_id", min_length=1, description="run_id + source + file hash prefix."
    )
    source_file: str = Field(alias="_source_file", min_length=1, description="Relative path.")
    source_row: int = Field(alias="_source_row", ge=0, description="Row number in the file.")
    row_hash: str = Field(
        alias="_row_hash", min_length=1, description="xxhash of business columns."
    )
    loaded_at: datetime = Field(alias="_loaded_at")


# Base order (RawMetadata, Source) puts the source columns first, then the metadata.


class RawSnowflakeActivity(RawMetadata, SnowflakeActivity):
    contract_name = "raw.snowflake__activity"
    contract_description = "Raw activity, one row per loaded source row."


class RawTeradataClient(RawMetadata, TeradataClient):
    contract_name = "raw.teradata__clnt"
    contract_description = "Raw client master and deltas."


class RawTeradataAdvisor(RawMetadata, TeradataAdvisor):
    contract_name = "raw.teradata__advsr"
    contract_description = "Raw advisor master."


class RawTeradataAssignment(RawMetadata, TeradataAssignment):
    contract_name = "raw.teradata__advsr_asgn"
    contract_description = "Raw advisor assignment events."


class RawTeradataBranch(RawMetadata, TeradataBranch):
    contract_name = "raw.teradata__brnch"
    contract_description = "Raw branch master."


RAW_CONTRACTS: tuple[type[Contract], ...] = (
    RawSnowflakeActivity,
    RawTeradataClient,
    RawTeradataAdvisor,
    RawTeradataAssignment,
    RawTeradataBranch,
)
