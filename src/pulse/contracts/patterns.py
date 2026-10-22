"""Identifier formats shared by contracts and validation."""

from __future__ import annotations

ACTIVITY_ID = r"^ACT-[0-9a-f]{12}$"
ADVISOR_ID = r"^ADV-\d{5}$"
CLIENT_ID = r"^CLI-\d{8}$"
BRANCH_ID = r"^BR-\d{4}$"
ASSIGNMENT_ID = r"^ASG-\d{8}$"
PORTFOLIO_ID = r"^PRT-\d{6}$"
PORTFOLIO_ASSIGNMENT_ID = r"^PAS-\d{8}$"
DISTRICT_CODE = r"^[A-Z]{3}$"
ISO_WEEK_ID = r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$"
RULE_ID = r"^DQ\d{3}$"
FACT_ID = r"^F\d+$"
SHA256 = r"^[0-9a-f]{64}$"

# Canadian FSA: no D, F, I, O, Q, U anywhere; W and Z never first.
FSA = r"^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]$"
FSA_OR_UNKNOWN = r"^([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]|UNK)$"
POSTAL_CODE = r"^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z] \d[ABCEGHJ-NPRSTV-Z]\d$"

FISCAL_QUARTER_ID = r"^FY\d{2}-Q[1-4]$"
