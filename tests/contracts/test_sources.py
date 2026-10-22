from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from pulse.contracts import column_names
from pulse.contracts.base import Contract
from pulse.contracts.sources import (
    SnowflakeActivity,
    TeradataAdvisor,
    TeradataAssignment,
    TeradataBranch,
    TeradataClient,
    TeradataPortfolio,
    TeradataPortfolioAssignment,
)


def _reject(model: type[Contract], row: dict[str, Any], **changes: Any) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**row, **changes})


def _accept(model: type[Contract], row: dict[str, Any], **changes: Any) -> None:
    model.model_validate({**row, **changes})


# ── Column lists pin the data dictionary (PLAN.md §6.1–6.2) ─────────────────


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (
            SnowflakeActivity,
            "ACTIVITY_ID ADVISOR_ID CLIENT_ID BRANCH_ID ACTIVITY_TYPE CHANNEL STATUS OUTCOME "
            "PRODUCT_LINE SCHEDULED_TS ACTIVITY_TS DURATION_MIN BOOKED_FROM_ACTIVITY_ID "
            "CREATED_TS UPDATED_TS _EXTRACTED_AT",
        ),
        (
            TeradataClient,
            "CLNT_ID CLNT_SINCE_DT BRTH_YR SEG_CD PSTL_CD PROV_CD PRIM_BRNCH_ID STAT_CD "
            "LAST_UPD_TS PRTF_ID",
        ),
        (TeradataAdvisor, "ADVSR_ID ADVSR_NM ROLE_CD HIRE_DT TERM_DT LAST_UPD_TS"),
        (TeradataAssignment, "ASGN_ID ADVSR_ID BRNCH_ID ROLE_CD EFF_DT RSN_CD LAST_UPD_TS"),
        (TeradataBranch, "BRNCH_ID BRNCH_NM DIST_CD FSA_CD OPEN_DT CLOSE_DT LAST_UPD_TS"),
        (TeradataPortfolio, "PRTF_ID BRNCH_ID OPEN_DT CLOSE_DT LAST_UPD_TS"),
        (
            TeradataPortfolioAssignment,
            "PASGN_ID PRTF_ID ADVSR_ID EFF_DT RSN_CD LAST_UPD_TS",
        ),
    ],
)
def test_columns_match_dictionary(model: type[Contract], expected: str) -> None:
    assert column_names(model) == expected.split()


# ── Valid rows ──────────────────────────────────────────────────────────────


def test_valid_rows_pass(
    activity_row: dict[str, Any],
    client_row: dict[str, Any],
    advisor_row: dict[str, Any],
    assignment_row: dict[str, Any],
    branch_row: dict[str, Any],
) -> None:
    _accept(SnowflakeActivity, activity_row)
    _accept(TeradataClient, client_row)
    _accept(TeradataAdvisor, advisor_row)
    _accept(TeradataAssignment, assignment_row)
    _accept(TeradataBranch, branch_row)


def test_snake_case_names_also_populate(activity_row: dict[str, Any]) -> None:
    row = SnowflakeActivity.model_validate(activity_row)
    again = SnowflakeActivity.model_validate(row.model_dump())
    assert again == row
    assert set(row.model_dump(by_alias=True)) == set(activity_row)


# ── DQ001: required keys ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "column", ["ACTIVITY_ID", "ADVISOR_ID", "BRANCH_ID", "ACTIVITY_TS", "_EXTRACTED_AT"]
)
def test_activity_required_columns_reject_null(activity_row: dict[str, Any], column: str) -> None:
    _reject(SnowflakeActivity, activity_row, **{column: None})


@pytest.mark.parametrize(
    "column",
    [
        "CLIENT_ID",
        "OUTCOME",
        "PRODUCT_LINE",
        "SCHEDULED_TS",
        "DURATION_MIN",
        "BOOKED_FROM_ACTIVITY_ID",
    ],
)
def test_activity_optional_columns_accept_null(activity_row: dict[str, Any], column: str) -> None:
    _accept(SnowflakeActivity, activity_row, **{column: None})


def test_missing_required_column_rejected(activity_row: dict[str, Any]) -> None:
    row = dict(activity_row)
    del row["STATUS"]
    with pytest.raises(ValidationError):
        SnowflakeActivity.model_validate(row)


def test_unknown_column_rejected(activity_row: dict[str, Any]) -> None:
    # Ingestion drops extra columns with a WARN (DQ006) before validating rows.
    _reject(SnowflakeActivity, activity_row, SURPRISE="x")


# ── DQ002: enums ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "column", ["ACTIVITY_TYPE", "CHANNEL", "STATUS", "OUTCOME", "PRODUCT_LINE"]
)
def test_activity_enums_reject_unknown(activity_row: dict[str, Any], column: str) -> None:
    _reject(SnowflakeActivity, activity_row, **{column: "NOT_A_VALUE"})


def test_activity_enums_are_case_sensitive(activity_row: dict[str, Any]) -> None:
    _reject(SnowflakeActivity, activity_row, ACTIVITY_TYPE="appointment")


@pytest.mark.parametrize(
    ("column", "bad"), [("SEG_CD", "VIP"), ("PROV_CD", "YT"), ("STAT_CD", "X")]
)
def test_client_enums_reject_unknown(client_row: dict[str, Any], column: str, bad: str) -> None:
    _reject(TeradataClient, client_row, **{column: bad})


def test_advisor_and_assignment_enums(
    advisor_row: dict[str, Any], assignment_row: dict[str, Any]
) -> None:
    _reject(TeradataAdvisor, advisor_row, ROLE_CD="CEO")
    _reject(TeradataAssignment, assignment_row, RSN_CD="RETIRE")


# ── DQ003 / DQ004: ranges ───────────────────────────────────────────────────


@pytest.mark.parametrize(("minutes", "ok"), [(-1, False), (0, True), (480, True), (481, False)])
def test_duration_bounds(activity_row: dict[str, Any], minutes: int, ok: bool) -> None:
    if ok:
        _accept(SnowflakeActivity, activity_row, DURATION_MIN=minutes)
    else:
        _reject(SnowflakeActivity, activity_row, DURATION_MIN=minutes)


def test_activity_before_2015_rejected(activity_row: dict[str, Any]) -> None:
    _reject(SnowflakeActivity, activity_row, ACTIVITY_TS="2014-12-31T23:59:00Z")


def test_activity_after_extract_skew_rejected(activity_row: dict[str, Any]) -> None:
    _accept(SnowflakeActivity, activity_row, ACTIVITY_TS="2026-10-13T05:59:00Z")
    _reject(SnowflakeActivity, activity_row, ACTIVITY_TS="2026-10-13T06:01:00Z")


def test_naive_timestamps_are_treated_as_utc(activity_row: dict[str, Any]) -> None:
    _accept(
        SnowflakeActivity,
        activity_row,
        ACTIVITY_TS="2026-10-06T14:05:00",
        _EXTRACTED_AT="2026-10-12T06:00:00",
    )


def test_unparseable_types_rejected(activity_row: dict[str, Any]) -> None:
    _reject(SnowflakeActivity, activity_row, DURATION_MIN="forty")
    _reject(SnowflakeActivity, activity_row, ACTIVITY_TS="last tuesday")


def test_term_before_hire_rejected(advisor_row: dict[str, Any]) -> None:
    _accept(TeradataAdvisor, advisor_row, TERM_DT="2025-01-01")
    _reject(TeradataAdvisor, advisor_row, TERM_DT="2019-05-05")


def test_birth_year_bounds(client_row: dict[str, Any]) -> None:
    _reject(TeradataClient, client_row, BRTH_YR=1900)
    _reject(TeradataClient, client_row, BRTH_YR=2020)


# ── Identifier formats ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("column", "bad"),
    [
        ("ACTIVITY_ID", "ACT-XYZ"),
        ("ADVISOR_ID", "ADV-123"),
        ("CLIENT_ID", "CLI-12"),
        ("BRANCH_ID", "BR-12"),
        ("BOOKED_FROM_ACTIVITY_ID", "nope"),
    ],
)
def test_activity_id_formats(activity_row: dict[str, Any], column: str, bad: str) -> None:
    _reject(SnowflakeActivity, activity_row, **{column: bad})


@pytest.mark.parametrize("fsa", ["M6K", "H2X", "V6B", "A1C"])
def test_branch_fsa_accepts_real_shapes(branch_row: dict[str, Any], fsa: str) -> None:
    _accept(TeradataBranch, branch_row, FSA_CD=fsa)


@pytest.mark.parametrize("fsa", ["D1A", "W1A", "M6", "m6k", "M6K 1A1", "UNK"])
def test_branch_fsa_rejects_invalid(branch_row: dict[str, Any], fsa: str) -> None:
    _reject(TeradataBranch, branch_row, FSA_CD=fsa)


@pytest.mark.parametrize("postal", ["m5v3l9", "M5V-3L9", "M5V 3L9 ", "90210", None])
def test_client_postal_code_is_not_validated_at_source(
    client_row: dict[str, Any], postal: str | None
) -> None:
    # Dirty postal codes are normalized in staging (DQ011), not quarantined.
    _accept(TeradataClient, client_row, PSTL_CD=postal)


# ── Portfolios (PLAN.md §6.2, #220) ──────────────────────────────────────────

PORTFOLIO = {
    "PRTF_ID": "PRT-000101",
    "BRNCH_ID": "BR-0101",
    "OPEN_DT": "2019-04-01",
    "CLOSE_DT": None,
    "LAST_UPD_TS": "2026-10-12T06:00:00Z",
}
PORTFOLIO_ASSIGNMENT = {
    "PASGN_ID": "PAS-00000001",
    "PRTF_ID": "PRT-000101",
    "ADVSR_ID": "ADV-00141",
    "EFF_DT": "2024-02-19",
    "RSN_CD": "HANDOVER",
    "LAST_UPD_TS": "2026-10-12T06:00:00Z",
}


def test_portfolio_rows() -> None:
    _accept(TeradataPortfolio, PORTFOLIO)
    _accept(TeradataPortfolio, PORTFOLIO, CLOSE_DT="2026-01-31")
    _reject(TeradataPortfolio, PORTFOLIO, CLOSE_DT="2019-03-31")
    _reject(TeradataPortfolio, PORTFOLIO, PRTF_ID="PRT-101")
    _accept(TeradataPortfolioAssignment, PORTFOLIO_ASSIGNMENT)
    _reject(TeradataPortfolioAssignment, PORTFOLIO_ASSIGNMENT, RSN_CD="RETIRE")
    _reject(TeradataPortfolioAssignment, PORTFOLIO_ASSIGNMENT, ADVSR_ID=None)


def test_client_portfolio_is_required(client_row: dict[str, Any]) -> None:
    # The book owner is the portfolio's holder, so a client without one has no owner.
    assert TeradataClient.model_validate(client_row).portfolio_id == "PRT-000123"
    _reject(TeradataClient, client_row, PRTF_ID=None)
    _reject(TeradataClient, client_row, PRTF_ID="P-1")
    without = {k: v for k, v in client_row.items() if k != "PRTF_ID"}
    with pytest.raises(ValidationError):
        TeradataClient.model_validate(without)
