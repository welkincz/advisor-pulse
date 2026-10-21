"""Controlled vocabularies, defined once (PLAN.md §5–§8)."""

from __future__ import annotations

from enum import StrEnum


class ActivityType(StrEnum):
    CALL_OUT = "CALL_OUT"
    CALL_IN = "CALL_IN"
    APPOINTMENT = "APPOINTMENT"
    REVIEW = "REVIEW"


class Channel(StrEnum):
    IN_BRANCH = "IN_BRANCH"
    PHONE = "PHONE"
    VIDEO = "VIDEO"


class ActivityStatus(StrEnum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class Outcome(StrEnum):
    NONE = "NONE"
    FOLLOW_UP = "FOLLOW_UP"
    PLAN_CREATED = "PLAN_CREATED"
    PRODUCT_OPENED = "PRODUCT_OPENED"
    REFERRAL = "REFERRAL"


class ProductLine(StrEnum):
    DEPOSITS = "DEPOSITS"
    LENDING = "LENDING"
    MORTGAGE = "MORTGAGE"
    INVESTING = "INVESTING"
    INSURANCE = "INSURANCE"


class Segment(StrEnum):
    MASS = "MASS"
    MASS_AFFLUENT = "MAFF"
    AFFLUENT = "AFFL"
    SMALL_BUSINESS = "SMBS"


class Role(StrEnum):
    ASSOCIATE = "ASSOC"
    ADVISOR = "ADVSR"
    SENIOR_ADVISOR = "SNR_ADVSR"
    BRANCH_MANAGER = "BR_MGR"


class AssignmentReason(StrEnum):
    HIRE = "HIRE"
    TRANSFER = "TRANSFER"
    PROMOTION = "PROMOTION"
    TERM = "TERM"


class ClientStatus(StrEnum):
    ACTIVE = "A"
    CLOSED = "C"


class Province(StrEnum):
    """Provinces in scope. Territories are out of scope for the fictional network."""

    ON = "ON"
    QC = "QC"
    BC = "BC"
    AB = "AB"
    SK = "SK"
    MB = "MB"
    NS = "NS"
    PE = "PE"
    NB = "NB"
    NL = "NL"


class RegionCode(StrEnum):
    """Regions follow the provinces, as a Canadian bank's branch network usually does."""

    ONTARIO = "ON"
    QUEBEC = "QC"
    BRITISH_COLUMBIA = "BC"
    ALBERTA = "AB"
    SASKATCHEWAN = "SK"
    MANITOBA = "MB"
    NOVA_SCOTIA = "NS"
    PRINCE_EDWARD_ISLAND = "PE"
    NEW_BRUNSWICK = "NB"
    NEWFOUNDLAND_AND_LABRADOR = "NL"


class OrgLevel(StrEnum):
    NATIONAL = "NATIONAL"
    REGION = "REGION"
    DISTRICT = "DISTRICT"
    BRANCH = "BRANCH"


class RunType(StrEnum):
    WEEKLY = "WEEKLY"
    BACKFILL = "BACKFILL"
    MANUAL = "MANUAL"


class StageStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    WARN = "WARN"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class LoadStatus(StrEnum):
    LOADED = "LOADED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    FAILED = "FAILED"


class CheckSeverity(StrEnum):
    WARN = "WARN"
    FAIL = "FAIL"


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class DqAction(StrEnum):
    QUARANTINE = "QUARANTINE"
    FAIL_FILE = "FAIL_FILE"
    DEDUPE = "DEDUPE"
    NORMALIZE = "NORMALIZE"
    MAP_UNKNOWN = "MAP_UNKNOWN"
    KEEP_FLAGGED = "KEEP_FLAGGED"
    TEST_ERROR = "TEST_ERROR"
    RUN_CHECK = "RUN_CHECK"


class KpiCode(StrEnum):
    """KPI codes from PLAN.md §7."""

    ACT_PER_ADV = "ACT_PER_ADV"
    CALLS_OUT = "CALLS_OUT"
    APPT_BOOKED = "APPT_BOOKED"
    CALL_TO_APPT = "CALL_TO_APPT"
    SHOW_RATE = "SHOW_RATE"
    APPT_CONV = "APPT_CONV"
    CLIENTS_CONTACTED = "CLIENTS_CONTACTED"
    COVERAGE_13W = "COVERAGE_13W"
    AVG_MEET_MIN = "AVG_MEET_MIN"
    NO_SHOW_RATE = "NO_SHOW_RATE"
    LATE_RATE = "LATE_RATE"
    QUAR_RATE = "QUAR_RATE"


class ReportFlag(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"
    ANOMALY = "ANOMALY"


class PipelineNodeKind(StrEnum):
    SOURCE = "SOURCE"
    STAGE = "STAGE"
    DBT_LAYER = "DBT_LAYER"
    OUTPUT = "OUTPUT"
