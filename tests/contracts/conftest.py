from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def activity_row() -> dict[str, Any]:
    return {
        "ACTIVITY_ID": "ACT-0a1b2c3d4e5f",
        "ADVISOR_ID": "ADV-00123",
        "CLIENT_ID": "CLI-00004567",
        "BRANCH_ID": "BR-0412",
        "ACTIVITY_TYPE": "APPOINTMENT",
        "CHANNEL": "IN_BRANCH",
        "STATUS": "COMPLETED",
        "OUTCOME": "PLAN_CREATED",
        "PRODUCT_LINE": "INVESTING",
        "SCHEDULED_TS": "2026-10-06T14:00:00Z",
        "ACTIVITY_TS": "2026-10-06T14:05:00Z",
        "DURATION_MIN": 45,
        "BOOKED_FROM_ACTIVITY_ID": "ACT-ffffffffffff",
        "CREATED_TS": "2026-09-29T15:00:00Z",
        "UPDATED_TS": "2026-10-06T15:00:00Z",
        "_EXTRACTED_AT": "2026-10-12T06:00:00Z",
    }


@pytest.fixture
def client_row() -> dict[str, Any]:
    return {
        "CLNT_ID": "CLI-00004567",
        "CLNT_SINCE_DT": "2014-03-02",
        "BRTH_YR": 1978,
        "SEG_CD": "MAFF",
        "PSTL_CD": "m5v3l9",
        "PROV_CD": "ON",
        "PRIM_BRNCH_ID": "BR-0412",
        "STAT_CD": "A",
        "LAST_UPD_TS": "2026-10-11T22:00:00Z",
        "PRTF_ID": "PRT-000123",
    }


@pytest.fixture
def advisor_row() -> dict[str, Any]:
    return {
        "ADVSR_ID": "ADV-00123",
        "ADVSR_NM": "Jordan Tremblay",
        "ROLE_CD": "SNR_ADVSR",
        "HIRE_DT": "2019-05-06",
        "TERM_DT": None,
        "LAST_UPD_TS": "2026-10-11T22:00:00Z",
    }


@pytest.fixture
def assignment_row() -> dict[str, Any]:
    return {
        "ASGN_ID": "ASG-00000042",
        "ADVSR_ID": "ADV-00123",
        "BRNCH_ID": "BR-0412",
        "ROLE_CD": "ADVSR",
        "EFF_DT": "2024-02-05",
        "RSN_CD": "TRANSFER",
        "LAST_UPD_TS": "2026-10-11T22:00:00Z",
    }


@pytest.fixture
def branch_row() -> dict[str, Any]:
    return {
        "BRNCH_ID": "BR-0412",
        "BRNCH_NM": "Liberty Village Branch",
        "DIST_CD": "GTA",
        "FSA_CD": "M6K",
        "OPEN_DT": "2008-09-15",
        "CLOSE_DT": None,
        "LAST_UPD_TS": "2026-10-11T22:00:00Z",
    }
