"""Source-system contracts (PLAN.md §6.1–6.2).

Columns keep the source's own names via aliases: ``UPPER_SNAKE`` for the 'Snowflake' unload and
Teradata-style abbreviations for the 'Teradata' EDW. A row that fails these models is quarantined
at ingest (rules DQ001–DQ005). Postal codes are deliberately unconstrained here: they are
normalized in staging, not rejected.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pydantic import Field, model_validator

from pulse.contracts import patterns
from pulse.contracts.base import Contract
from pulse.contracts.enums import (
    ActivityStatus,
    ActivityType,
    AssignmentReason,
    Channel,
    ClientStatus,
    Outcome,
    PortfolioAssignmentReason,
    ProductLine,
    Province,
    Role,
    Segment,
)

EARLIEST_ACTIVITY = datetime(2015, 1, 1, tzinfo=UTC)
MAX_FUTURE_SKEW = timedelta(days=1)
MAX_DURATION_MIN = 480


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ── 'Snowflake' ──────────────────────────────────────────────────────────────


class SnowflakeActivity(Contract):
    contract_name = "snowflake__activity"
    contract_description = (
        "Advisor activity facts, unloaded weekly to "
        "sources/snowflake/activity/extract_date=YYYY-MM-DD/part-NNN.parquet."
    )

    activity_id: str = Field(
        alias="ACTIVITY_ID", pattern=patterns.ACTIVITY_ID, description="Natural key."
    )
    advisor_id: str = Field(alias="ADVISOR_ID", pattern=patterns.ADVISOR_ID)
    client_id: str | None = Field(
        default=None,
        alias="CLIENT_ID",
        pattern=patterns.CLIENT_ID,
        description="Null for prospecting calls.",
    )
    branch_id: str = Field(
        alias="BRANCH_ID",
        pattern=patterns.BRANCH_ID,
        description="Branch where the activity was logged.",
    )
    activity_type: ActivityType = Field(alias="ACTIVITY_TYPE")
    channel: Channel = Field(alias="CHANNEL")
    status: ActivityStatus = Field(alias="STATUS")
    outcome: Outcome | None = Field(default=None, alias="OUTCOME")
    product_line: ProductLine | None = Field(default=None, alias="PRODUCT_LINE")
    scheduled_ts: datetime | None = Field(
        default=None,
        alias="SCHEDULED_TS",
        description="Scheduled time for appointments and reviews (UTC).",
    )
    activity_ts: datetime = Field(
        alias="ACTIVITY_TS", description="When it happened, or was due (UTC)."
    )
    duration_min: int | None = Field(default=None, alias="DURATION_MIN", ge=0, le=MAX_DURATION_MIN)
    booked_from_activity_id: str | None = Field(
        default=None,
        alias="BOOKED_FROM_ACTIVITY_ID",
        pattern=patterns.ACTIVITY_ID,
        description="For appointments booked on a call: the call's ACTIVITY_ID.",
    )
    created_ts: datetime = Field(alias="CREATED_TS")
    updated_ts: datetime = Field(alias="UPDATED_TS")
    extracted_at: datetime = Field(
        alias="_EXTRACTED_AT", description="Extract time; the watermark column."
    )

    @model_validator(mode="after")
    def _activity_ts_in_range(self) -> SnowflakeActivity:
        """DQ004: not before 2015, not more than a day past the extract."""
        ts = _as_utc(self.activity_ts)
        if ts < EARLIEST_ACTIVITY:
            raise ValueError("ACTIVITY_TS is before 2015-01-01")
        if ts > _as_utc(self.extracted_at) + MAX_FUTURE_SKEW:
            raise ValueError("ACTIVITY_TS is more than 1 day after _EXTRACTED_AT")
        return self


# ── 'Teradata' ───────────────────────────────────────────────────────────────


class TeradataClient(Contract):
    contract_name = "teradata__clnt"
    contract_description = (
        "Client master (CLNT) in sources/teradata/edw.sqlite; "
        "daily deltas in client_YYYYMMDD.csv share these columns."
    )

    client_id: str = Field(alias="CLNT_ID", pattern=patterns.CLIENT_ID)
    client_since_date: date = Field(alias="CLNT_SINCE_DT", description="Relationship start.")
    birth_year: int = Field(alias="BRTH_YR", ge=1920, le=2010)
    segment_code: Segment = Field(alias="SEG_CD")
    postal_code: str | None = Field(
        default=None, alias="PSTL_CD", description="Raw postal code; normalized in staging."
    )
    province_code: Province = Field(alias="PROV_CD")
    primary_branch_id: str = Field(alias="PRIM_BRNCH_ID", pattern=patterns.BRANCH_ID)
    status_code: ClientStatus = Field(alias="STAT_CD")
    last_updated_ts: datetime = Field(alias="LAST_UPD_TS", description="Watermark column.")
    portfolio_id: str = Field(
        alias="PRTF_ID",
        pattern=patterns.PORTFOLIO_ID,
        description="Portfolio the client belongs to; its holder at week end owns the book.",
    )


class TeradataAdvisor(Contract):
    contract_name = "teradata__advsr"
    contract_description = "Advisor master (ADVSR) in sources/teradata/edw.sqlite."

    advisor_id: str = Field(alias="ADVSR_ID", pattern=patterns.ADVISOR_ID)
    advisor_name: str = Field(alias="ADVSR_NM", min_length=1, description="Synthetic name.")
    role_code: Role = Field(alias="ROLE_CD")
    hire_date: date = Field(alias="HIRE_DT")
    term_date: date | None = Field(default=None, alias="TERM_DT")
    last_updated_ts: datetime = Field(alias="LAST_UPD_TS", description="Watermark column.")

    @model_validator(mode="after")
    def _term_after_hire(self) -> TeradataAdvisor:
        if self.term_date is not None and self.term_date < self.hire_date:
            raise ValueError("TERM_DT is before HIRE_DT")
        return self


class TeradataAssignment(Contract):
    contract_name = "teradata__advsr_asgn"
    contract_description = (
        "Advisor assignment events (ADVSR_ASGN) in sources/teradata/edw.sqlite; "
        "the input to SCD2 advisor history."
    )

    assignment_id: str = Field(alias="ASGN_ID", pattern=patterns.ASSIGNMENT_ID)
    advisor_id: str = Field(alias="ADVSR_ID", pattern=patterns.ADVISOR_ID)
    branch_id: str = Field(alias="BRNCH_ID", pattern=patterns.BRANCH_ID)
    role_code: Role = Field(alias="ROLE_CD")
    effective_date: date = Field(alias="EFF_DT")
    reason_code: AssignmentReason = Field(alias="RSN_CD")
    last_updated_ts: datetime = Field(alias="LAST_UPD_TS", description="Watermark column.")


class TeradataBranch(Contract):
    contract_name = "teradata__brnch"
    contract_description = "Branch master (BRNCH) in sources/teradata/edw.sqlite."

    branch_id: str = Field(alias="BRNCH_ID", pattern=patterns.BRANCH_ID)
    branch_name: str = Field(alias="BRNCH_NM", min_length=1)
    district_code: str = Field(alias="DIST_CD", pattern=patterns.DISTRICT_CODE)
    fsa_code: str = Field(alias="FSA_CD", pattern=patterns.FSA)
    open_date: date = Field(alias="OPEN_DT")
    close_date: date | None = Field(default=None, alias="CLOSE_DT")
    last_updated_ts: datetime = Field(alias="LAST_UPD_TS", description="Watermark column.")


class TeradataPortfolio(Contract):
    contract_name = "teradata__prtf"
    contract_description = (
        "Portfolio master (PRTF) in sources/teradata/edw.sqlite: a group of clients managed "
        "by one advisor at a time, belonging to one branch (its transit)."
    )

    portfolio_id: str = Field(alias="PRTF_ID", pattern=patterns.PORTFOLIO_ID)
    branch_id: str = Field(
        alias="BRNCH_ID", pattern=patterns.BRANCH_ID, description="Transit: the owning branch."
    )
    open_date: date = Field(alias="OPEN_DT")
    close_date: date | None = Field(default=None, alias="CLOSE_DT")
    last_updated_ts: datetime = Field(alias="LAST_UPD_TS", description="Watermark column.")

    @model_validator(mode="after")
    def _close_after_open(self) -> TeradataPortfolio:
        if self.close_date is not None and self.close_date < self.open_date:
            raise ValueError("CLOSE_DT is before OPEN_DT")
        return self


class TeradataPortfolioAssignment(Contract):
    contract_name = "teradata__prtf_asgn"
    contract_description = (
        "Portfolio assignment events (PRTF_ASGN) in sources/teradata/edw.sqlite: who holds "
        "each portfolio from EFF_DT on; the input to SCD2 portfolio history."
    )

    portfolio_assignment_id: str = Field(alias="PASGN_ID", pattern=patterns.PORTFOLIO_ASSIGNMENT_ID)
    portfolio_id: str = Field(alias="PRTF_ID", pattern=patterns.PORTFOLIO_ID)
    advisor_id: str = Field(alias="ADVSR_ID", pattern=patterns.ADVISOR_ID)
    effective_date: date = Field(alias="EFF_DT")
    reason_code: PortfolioAssignmentReason = Field(alias="RSN_CD")
    last_updated_ts: datetime = Field(alias="LAST_UPD_TS", description="Watermark column.")


SOURCE_CONTRACTS: tuple[type[Contract], ...] = (
    SnowflakeActivity,
    TeradataClient,
    TeradataAdvisor,
    TeradataAssignment,
    TeradataBranch,
    TeradataPortfolio,
    TeradataPortfolioAssignment,
)
