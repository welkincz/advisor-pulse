"""Defect manifest contract (PLAN.md §5, rule DQ033).

The ground truth of what was injected into a batch of synthetic sources. The generator writes
one per week (``defects/YYYY-Www.json``); the fixtures write one for all their weeks
(``fixtures/defects.json``). Tests reconcile the pipeline against it: every DQ001–DQ005 entry
must be quarantined, every DQ010 entry deduplicated, and so on.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from pulse.contracts import patterns
from pulse.contracts.base import Contract
from pulse.contracts.enums import DqAction
from pulse.contracts.exports import Document, IsoWeek


class DefectKind(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    RESENT_UPDATE = "RESENT_UPDATE"
    NULL_ACTIVITY_ID = "NULL_ACTIVITY_ID"
    INVALID_ENUM = "INVALID_ENUM"
    DURATION_OUT_OF_RANGE = "DURATION_OUT_OF_RANGE"
    ACTIVITY_TS_OUT_OF_RANGE = "ACTIVITY_TS_OUT_OF_RANGE"
    UNPARSEABLE_VALUE = "UNPARSEABLE_VALUE"
    UNKNOWN_ADVISOR = "UNKNOWN_ADVISOR"
    DIRTY_POSTAL_CODE = "DIRTY_POSTAL_CODE"
    LATE_ARRIVING = "LATE_ARRIVING"
    ADVISOR_TRANSFER = "ADVISOR_TRANSFER"
    ADVISOR_PROMOTION = "ADVISOR_PROMOTION"
    ADVISOR_TERM = "ADVISOR_TERM"
    CLIENT_REASSIGNMENT = "CLIENT_REASSIGNMENT"
    UNKNOWN_PORTFOLIO = "UNKNOWN_PORTFOLIO"


class Defect(Contract):
    contract_name = "defect"

    kind: DefectKind
    iso_week_id: IsoWeek = Field(description="Week of the batch that carries the defect.")
    source: str = Field(min_length=1, description="'snowflake' or 'teradata'.")
    table_name: str = Field(min_length=1, description="Source table, e.g. 'activity', 'CLNT'.")
    file: str = Field(min_length=1, description="Path relative to the sources root.")
    row: int | None = Field(
        default=None,
        ge=0,
        description="0-based data row in the file (header excluded); null for SQLite tables.",
    )
    natural_key: str | None = Field(
        default=None, description="ACTIVITY_ID, CLNT_ID or ASGN_ID of the row, when it has one."
    )
    column: str | None = Field(default=None, description="Source column the defect is in.")
    raw_value: str | None = Field(default=None, description="The value as written, as text.")
    expected_value: str | None = Field(
        default=None,
        description=(
            "What the pipeline should produce: normalized postal code or 'UNK', final status, "
            "activity week of a late row, new branch or role."
        ),
    )
    rule_id: str | None = Field(
        default=None, pattern=patterns.RULE_ID, description="DQ rule that must catch it."
    )
    action: DqAction | None = Field(default=None, description="Expected handling.")
    detail: str = Field(min_length=1)


class DefectManifest(Document):
    contract_name = "defect_manifest"
    contract_description = (
        "Ground truth of injected defects: defects/YYYY-Www.json from the generator, "
        "fixtures/defects.json for the fixtures."
    )

    generated_at: datetime
    seed: int
    iso_weeks: list[IsoWeek] = Field(min_length=1)
    defects: list[Defect]


DEFECT_CONTRACTS: tuple[type[Contract], ...] = (DefectManifest,)
