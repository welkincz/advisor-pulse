"""Weekly roster includes partial employment without duplicating SCD2 changes (#312)."""

from pathlib import Path

import duckdb
from jinja2 import Environment

ROOT = Path(__file__).parents[2]


def _sql(path: str) -> str:
    # Render the actual model and date macros; no second copy of the roster logic.
    template = (ROOT / "dbt/macros/dates.sql").read_text() + (ROOT / path).read_text()
    return Environment().from_string(template).render(ref=lambda name: name)


def test_partial_week_employment_gets_one_zero_activity_row_and_one_denominator() -> None:
    with duckdb.connect() as con:
        con.execute("""
            create table int_activity_enriched as select
                '2026-W40' as iso_week_id, false as is_advisor_matched,
                'UNKNOWN' as advisor_id, 'BR-1' as attributed_branch_id,
                'CALL_OUT' as activity_type, 0 as duration_min,
                null::varchar as client_id, 'COMPLETED' as status,
                null::timestamptz as scheduled_ts, null::timestamptz as created_ts,
                null::varchar as outcome, null::varchar as booked_from_activity_id;
            create table dim_activity_type as select
                'CALL_OUT' as activity_type, false as is_appointment_like,
                true as counts_as_contact;
            create table dim_date as select '2026-W40' as iso_week_id,
                date '2026-09-28' as week_start, date '2026-10-04' as week_end;
            create table int_contact_window as select '2026-W40' as iso_week_id,
                true as is_reported, false as is_window_complete;
            create table int_client_contact_12m (
                iso_week_id varchar, advisor_id varchar,
                transit_branch_id varchar, contacted_12m boolean);
            insert into int_client_contact_12m values
                ('2026-W40', 'HIRE-WED', 'BR-1', true);
            create table dim_org as select 'BR-1' as branch_id,
                'DIST-1' as district_code, 'REG-1' as region_code
                union all select 'BR-2', 'DIST-2', 'REG-2';
            create table int_advisor_history (
                advisor_id varchar, branch_id varchar, role_code varchar,
                valid_from date, valid_to date, assignment_id varchar);
        """)
        con.executemany(
            "insert into int_advisor_history values (?, ?, ?, ?, ?, ?)",
            [
                ("HIRE-WED", "BR-1", "ADVSR", "2026-09-30", "9999-12-31", "1"),
                ("HIRE-SUN", "BR-1", "ADVSR", "2026-10-04", "9999-12-31", "2"),
                ("TERM-WED", "BR-1", "ADVSR", "2020-01-01", "2026-09-30", "3"),
                ("TERM-MON", "BR-1", "ADVSR", "2020-01-01", "2026-09-28", "4"),
                ("HIRE-NEXT", "BR-1", "ADVSR", "2026-10-05", "9999-12-31", "5"),
                ("MANAGER", "BR-1", "BR_MGR", "2020-01-01", "9999-12-31", "6"),
                ("TRANSFER", "BR-1", "ADVSR", "2020-01-01", "2026-09-30", "7"),
                ("TRANSFER", "BR-2", "ADVSR", "2026-09-30", "9999-12-31", "8"),
                ("PROMOTION", "BR-1", "ADVSR", "2020-01-01", "2026-10-01", "9"),
                ("PROMOTION", "BR-1", "SNR_ADVSR", "2026-10-01", "9999-12-31", "10"),
                ("TO-MANAGER", "BR-1", "ADVSR", "2020-01-01", "2026-09-30", "11"),
                ("TO-MANAGER", "BR-1", "BR_MGR", "2026-09-30", "9999-12-31", "12"),
                ("FROM-MANAGER", "BR-1", "BR_MGR", "2020-01-01", "2026-09-30", "13"),
                ("FROM-MANAGER", "BR-2", "ADVSR", "2026-09-30", "9999-12-31", "14"),
            ],
        )
        con.execute(
            "create table int_kpi_events as " + _sql("dbt/models/intermediate/int_kpi_events.sql")
        )
        con.execute(
            "create table mart_advisor_weekly as "
            + _sql("dbt/models/marts/mart_advisor_weekly.sql")
        )
        rows = con.execute(
            "select advisor_id, branch_id, activities_completed, portfolio_clients,"
            " portfolio_contacted_12m from mart_advisor_weekly order by advisor_id"
        ).fetchall()
        assert rows == [
            ("FROM-MANAGER", "BR-2", 0, 0, 0),
            ("HIRE-SUN", "BR-1", 0, 0, 0),
            ("HIRE-WED", "BR-1", 0, 1, 1),
            ("PROMOTION", "BR-1", 0, 0, 0),
            ("TERM-WED", "BR-1", 0, 0, 0),
            ("TO-MANAGER", "BR-1", 0, 0, 0),
            ("TRANSFER", "BR-1", 0, 0, 0),
        ]
        assert con.execute("select sum(active_advisors) from int_kpi_events").fetchone() == (7,)
