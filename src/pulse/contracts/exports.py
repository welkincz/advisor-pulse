"""Export contracts for the web app and other consumers (PLAN.md §6.8–6.9, §11).

Tables are written to ``web/public/data/*.parquet``; documents to ``*.json``. Rates are
fractions in [0, 1] and null when their denominator is zero.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import Field

from pulse.contracts import patterns
from pulse.contracts.base import SCHEMA_VERSION, Contract
from pulse.contracts.enums import (
    CheckSeverity,
    CheckStatus,
    DqAction,
    KpiCode,
    OrgLevel,
    PipelineNodeKind,
    RegionCode,
    ReportFlag,
    RunType,
    StageStatus,
)

Count = Annotated[int, Field(ge=0)]
Rate = Annotated[float, Field(ge=0.0, le=1.0)]
IsoWeek = Annotated[str, Field(pattern=patterns.ISO_WEEK_ID)]
FactId = Annotated[str, Field(pattern=patterns.FACT_ID)]

# ── Tables (Parquet) ─────────────────────────────────────────────────────────


class AdvisorWeekly(Contract):
    contract_name = "advisor_weekly"
    contract_description = "mart_advisor_weekly: one row per advisor and ISO week (last 26 weeks)."

    iso_week_id: IsoWeek
    advisor_id: str = Field(pattern=patterns.ADVISOR_ID)
    branch_id: str = Field(pattern=patterns.BRANCH_ID, description="As-of branch for the week.")
    district_code: str = Field(pattern=patterns.DISTRICT_CODE)
    region_code: RegionCode
    activities_completed: Count
    calls_out: Count
    calls_in: Count
    appointments_booked: Count
    appointments_held: Count
    no_shows: Count
    conversions: Count
    unique_clients_contacted: Count
    book_size: Count
    clients_covered_13w: Count
    coverage_rate_13w: Rate | None = None
    avg_meeting_duration_min: float | None = Field(default=None, ge=0)


class OrgWeekly(Contract):
    contract_name = "org_weekly"
    contract_description = (
        "mart_org_weekly: one row per hierarchy node and ISO week, every level. "
        "Ratios are recomputed from summed parts, never averaged."
    )

    iso_week_id: IsoWeek
    level: OrgLevel
    node_id: str = Field(
        min_length=1, description="'CA' for national; region, district or branch code."
    )
    node_name: str = Field(min_length=1)
    parent_id: str | None = Field(default=None, description="Null for the national node.")
    active_advisors: Count
    activities_completed: Count
    calls_out: Count
    calls_in: Count
    appointments_booked: Count
    appointments_held: Count
    no_shows: Count
    conversions: Count
    unique_clients_contacted: Count
    book_size: Count
    clients_covered_13w: Count
    coverage_rate_13w: Rate | None = None
    avg_meeting_duration_min: float | None = Field(default=None, ge=0)
    activities_per_advisor: float | None = Field(default=None, ge=0)
    show_rate: Rate | None = None
    conversion_rate: Rate | None = None
    call_to_appt_rate: Rate | None = None


class OrgQuarterly(Contract):
    contract_name = "org_quarterly"
    contract_description = (
        "mart_org_quarterly: one row per hierarchy node and fiscal quarter (the fiscal year "
        "starts 1 November). Flows are summed, distinct clients counted over the quarter, "
        "stocks taken at the last reported week, ratios rebuilt from parts."
    )

    fiscal_quarter_id: str = Field(
        pattern=patterns.FISCAL_QUARTER_ID, description="e.g. 'FY26-Q1'."
    )
    fiscal_year: int = Field(ge=2000, le=2100)
    fiscal_quarter: int = Field(ge=1, le=4)
    quarter_start: date
    quarter_end: date
    first_week: IsoWeek
    last_week: IsoWeek = Field(description="Stocks (book, coverage) are taken at this week.")
    weeks_reported: int = Field(ge=1, le=14)
    weeks_in_quarter: int = Field(ge=12, le=14)
    is_complete: bool = Field(description="False for a quarter to date or a partial first quarter.")
    level: OrgLevel
    node_id: str = Field(min_length=1)
    node_name: str = Field(min_length=1)
    parent_id: str | None = None
    advisor_weeks: Count
    activities_completed: Count
    calls_out: Count
    calls_in: Count
    appointments_booked: Count
    booked_from_call: Count
    appointments_held: Count
    no_shows: Count
    conversions: Count
    unique_clients_contacted: Count
    book_size: Count
    clients_covered_13w: Count
    coverage_rate_13w: Rate | None = None
    avg_meeting_duration_min: float | None = Field(default=None, ge=0)
    activities_per_advisor: float | None = Field(default=None, ge=0)
    show_rate: Rate | None = None
    conversion_rate: Rate | None = None
    call_to_appt_rate: Rate | None = None


class WeeklyReport(Contract):
    contract_name = "weekly_report"
    contract_description = (
        "mart_weekly_report: long format, one row per (ISO week, node, KPI). "
        "Feeds the dashboard, Tableau and the AI narrative."
    )

    iso_week_id: IsoWeek
    level: OrgLevel
    node_id: str = Field(min_length=1)
    node_name: str = Field(min_length=1)
    parent_id: str | None = None
    kpi_code: KpiCode
    value: float | None = None
    prior_week_value: float | None = None
    wow_delta: float | None = None
    wow_pct: float | None = Field(default=None, description="Fraction: 0.042 means +4.2%.")
    trailing_13w_avg: float | None = None
    rank_in_parent: int | None = Field(default=None, ge=1, description="Dense rank, 1 = best.")
    peer_count: int | None = Field(default=None, ge=1)
    flag: ReportFlag


class GeoWeekly(Contract):
    contract_name = "geo_weekly"
    contract_description = "mart_geo_weekly: one row per FSA and ISO week (last 13 weeks)."

    iso_week_id: IsoWeek
    fsa_code: str = Field(pattern=patterns.FSA_OR_UNKNOWN)
    district_code: str = Field(pattern=patterns.DISTRICT_CODE)
    active_clients: Count
    clients_contacted_13w: Count
    coverage_rate_13w: Rate | None = None
    activities_completed: Count


class DqWeekly(Contract):
    contract_name = "dq_weekly"
    contract_description = "mart_dq_weekly: one row per data-quality rule and ISO week."

    iso_week_id: IsoWeek
    rule_id: str = Field(pattern=patterns.RULE_ID)
    rule_name: str = Field(min_length=1)
    action: DqAction
    rows_affected: Count
    rows_in_batch: Count
    rate: Rate | None = None


EXPORT_TABLE_CONTRACTS: tuple[type[Contract], ...] = (
    OrgWeekly,
    OrgQuarterly,
    AdvisorWeekly,
    WeeklyReport,
    GeoWeekly,
    DqWeekly,
)

# ── Documents (JSON) ─────────────────────────────────────────────────────────


class Document(Contract):
    contract_kind = "document"

    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^\d+\.\d+\.\d+$")


class ExportFile(Contract):
    contract_name = "export_file"
    name: str = Field(min_length=1, description="Path relative to the data/ directory.")
    sha256: str = Field(pattern=patterns.SHA256)
    rows: Count | None = Field(default=None, description="Null for JSON documents.")
    bytes: Count


class SummaryKpi(Contract):
    contract_name = "summary_kpi"
    kpi_code: KpiCode
    value: float | None = None
    prior_week_value: float | None = None
    wow_pct: float | None = None
    flag: ReportFlag


class Manifest(Document):
    contract_name = "manifest"
    contract_description = (
        "data/manifest.json: what the latest successful run exported, plus a national KPI "
        "summary so the overview can paint before DuckDB-WASM loads."
    )

    run_id: str = Field(min_length=1)
    generated_at: datetime
    latest_week: IsoWeek
    weeks_available: list[IsoWeek] = Field(min_length=1)
    files: list[ExportFile]
    summary: list[SummaryKpi] = Field(description="National KPIs for latest_week.")
    has_fsa_boundaries: bool = Field(
        default=False, description="True when geo/fsa.topo.json shipped (optional layer)."
    )


class StageAttempt(Contract):
    contract_name = "stage_attempt"
    stage: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    status: StageStatus
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: Count | None = None
    rows_in: Count | None = None
    rows_out: Count | None = None
    rows_quarantined: Count | None = None
    message: str | None = None


class RunCheck(Contract):
    contract_name = "run_check"
    check_id: str = Field(pattern=patterns.RULE_ID)
    severity: CheckSeverity
    status: CheckStatus
    observed: float | None = None
    expected: str | None = None
    message: str | None = None


class RunSummary(Contract):
    contract_name = "run_summary"
    run_id: str = Field(min_length=1)
    run_type: RunType
    iso_week_id: IsoWeek
    status: StageStatus = Field(description="Worst stage status of the run.")
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: Count | None = None
    git_sha: str | None = None
    stages: list[StageAttempt]
    checks: list[RunCheck]


class RunLogExport(Document):
    contract_name = "run_log"
    contract_description = (
        "data/run_log.json: the last 12 runs, newest first. Deployed even when a run fails."
    )

    generated_at: datetime
    runs: list[RunSummary] = Field(max_length=12)


class Position(Contract):
    contract_name = "position"
    x: float
    y: float


class PipelineNode(Contract):
    contract_name = "pipeline_node"
    id: str = Field(min_length=1, description="Stable across runs.")
    label: str = Field(min_length=1)
    kind: PipelineNodeKind
    stage: str | None = Field(default=None, description="Runner stage whose run_log rows map here.")
    models: list[str] = Field(default_factory=list, description="dbt models in a DBT_LAYER node.")
    position: Position


class PipelineEdge(Contract):
    contract_name = "pipeline_edge"
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)


class PipelineGraph(Document):
    contract_name = "pipeline_graph"
    contract_description = "data/pipeline_graph.json: nodes and edges for the React Flow view."

    nodes: list[PipelineNode] = Field(min_length=1)
    edges: list[PipelineEdge]


class NarrativeFact(Contract):
    contract_name = "narrative_fact"
    fact_id: str = Field(pattern=patterns.FACT_ID)
    node_id: str = Field(min_length=1)
    kpi_code: KpiCode
    iso_week_id: IsoWeek
    value: float | None = None
    prior_week_value: float | None = None
    wow_pct: float | None = None
    trailing_13w_avg: float | None = None
    rank_in_parent: int | None = Field(default=None, ge=1)
    peer_count: int | None = Field(default=None, ge=1)


class NarrativeBullet(Contract):
    contract_name = "narrative_bullet"
    text: str = Field(min_length=1)
    fact_ids: list[FactId] = Field(
        min_length=1, description="Every bullet cites at least one fact."
    )


class WatchItem(Contract):
    contract_name = "watch_item"
    node_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    fact_ids: list[FactId] = Field(min_length=1)


class NodeNarrative(Contract):
    contract_name = "node_narrative"
    node_id: str = Field(min_length=1)
    level: OrgLevel
    headline: str = Field(min_length=1)
    bullets: list[NarrativeBullet] = Field(min_length=1)
    watchlist: list[WatchItem] = Field(default_factory=list)
    facts_used: list[NarrativeFact] = Field(min_length=1)
    model: str | None = Field(default=None, description="Null for template fallbacks.")
    prompt_version: str = Field(min_length=1)
    validated: bool
    fallback: bool


class NarrativeFile(Document):
    contract_name = "narrative"
    contract_description = "data/narratives/YYYY-Www.json: one narrative per region and district."

    iso_week_id: IsoWeek
    generated_at: datetime
    narratives: list[NodeNarrative]


EXPORT_DOCUMENT_CONTRACTS: tuple[type[Contract], ...] = (
    Manifest,
    RunLogExport,
    PipelineGraph,
    NarrativeFile,
)
