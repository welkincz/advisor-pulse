from datetime import date

import pytest

from pulse.fiscal import (
    fiscal_month,
    fiscal_quarter_id,
    fiscal_year,
    quarter_bounds,
    week_fiscal_quarter_id,
    weeks_in_quarter,
)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2025, 10, 31), "FY25-Q4"),
        (date(2025, 11, 1), "FY26-Q1"),
        (date(2026, 1, 31), "FY26-Q1"),
        (date(2026, 2, 1), "FY26-Q2"),
        (date(2026, 7, 31), "FY26-Q3"),
        (date(2026, 10, 31), "FY26-Q4"),
    ],
)
def test_fiscal_quarters_start_in_november(day: date, expected: str) -> None:
    assert fiscal_quarter_id(day) == expected


def test_fiscal_year_and_month() -> None:
    assert fiscal_year(date(2025, 11, 1)) == 2026
    assert fiscal_year(date(2026, 10, 31)) == 2026
    assert [fiscal_month(date(2026, m, 1)) for m in (11, 12, 1, 10)] == [1, 2, 3, 12]


def test_quarter_bounds_cross_the_calendar_year() -> None:
    assert quarter_bounds(date(2026, 1, 20)) == (date(2025, 11, 1), date(2026, 1, 31))
    assert quarter_bounds(date(2026, 10, 18)) == (date(2026, 8, 1), date(2026, 10, 31))


def test_a_week_reports_in_the_quarter_holding_its_sunday() -> None:
    assert week_fiscal_quarter_id("2025-W44") == "FY26-Q1"  # Mon 27 Oct to Sun 2 Nov 2025
    assert week_fiscal_quarter_id("2025-W43") == "FY25-Q4"
    assert weeks_in_quarter("FY26-Q1") in (13, 14)
    # 2027-02-01 to 2027-04-30 holds only 12 Sundays (7 Feb to 25 Apr).
    assert weeks_in_quarter("FY27-Q2") == 12
    assert sum(weeks_in_quarter(f"FY26-Q{q}") for q in range(1, 5)) in (52, 53)
