# ADR 0005 — The 12-month contacted KPI: any advisor, a complete window, ratios from parts

- Status: Accepted
- Date: 2026-10-21
- Issues: #219, #223, #224, #225, #273

## Context

`PRTF_CONTACT_12M` replaces 13-week coverage as the lead KPI. The headline definition is
short ("of the clients in a portfolio, the share contacted in the last year"), but four
details decide whether the number can be trusted:

1. **Whose contact counts.** Only the holder's, or anyone's?
2. **What to show before a year of history exists.** The fixtures span 4 weeks, and a
   rebuilt warehouse starts its first year with a window that is too short.
3. **How to roll up** from portfolio to advisor, branch, district, region and national.
4. **What a quarter's value means.** A 12-month window already spans four quarters.

## Decision

- **Definition.** Active portfolio clients at week end with at least one completed
  contact activity (`counts_as_contact`) by **any advisor** whose Toronto activity date is
  in `(week_end − 12 months, week_end]`, divided by active portfolio clients at week end.
  `int_client_contact_12m` finds each client's last contact with one DuckDB `ASOF` join
  instead of scanning a year per week.
- **Any advisor counts.** The KPI is about the client: did they hear from the bank this
  year. When a portfolio is handed over it keeps the credit for the previous holder's
  calls, so the new holder does not start at 0%. The holder's own effort is still visible
  in activities per advisor, the secondary KPI.
- **Null until the window is complete.** `int_contact_window` marks a week complete when
  `week_end − 12 months` is on or after the first completed activity. Before that every
  rate is null. Counts are still published.
- **Ratios from parts.** Each mart carries `portfolio_clients` and
  `portfolio_contacted_12m`. Every level sums both and divides again; no level averages
  child rates.
- **Quarterly is a stock.** `mart_org_quarterly` takes the counts at each branch's own last
  reported week of the quarter, like `book_size`, and shows a rate only when that week's
  window is complete.
- **Fallback headline.** While the KPI is null, the narrative (`build_facts`) and the web
  (`defaultLead`, `leadFor`) lead with activities per advisor, and the KPI board hides a
  measure with no value in any shown week.

### Update (#273): a warm-up year

A null lead for the whole first reported year left FY25 without its headline. The
generator now starts its world 52 weeks before the first reported week, and the first
week loaded into a data directory carries those weeks' activity as an initial history
load. `int_contact_window.is_reported` starts the report at the first week with a full
window, so the warm-up year feeds the window but is never a reported week, and every
reported week has the lead KPI. A history shorter than a year (the fixtures) still reports
every week with the rate null, as above.

## Alternatives considered

- **Holder's own contacts only.** Rewards the person, not the outcome, and every handover
  would drop a portfolio to near zero for months.
- **Show a partial window early** (e.g. 4 months of data over a 12-month label). The
  number would rise every week for a year for no business reason and look like progress.
  Scaling it up would invent contacts.
- **Average child rates.** A 20-client portfolio would weigh as much as a 400-client one,
  and the national rate would not match the sum of its branches.
- **Quarterly as the average of weekly rates.** Each weekly value already covers a year,
  so averaging 13 of them double counts and blurs the quarter-end position.

## Consequences

- The KPI is null in the 4-week fixtures (and would be for the first year of a history
  without a warm-up), so CI tests compare the counts exactly and test the rate on its own
  unit tests.
- Numbers agree across views: an advisor, a branch and the nation are built from the same
  two counts.
- An advisor's score includes colleagues' calls to their clients. That is intended; a
  reader who wants effort looks at activities per advisor.
- The production report only shows the lead KPI after the full rebuild (ADR 0004).

## Code and tests

- Client-level window: [`int_client_contact_12m.sql`](../../dbt/models/intermediate/int_client_contact_12m.sql);
  unit test `int_client_contact_12m_counts_any_advisor_inside_twelve_months` in
  [`int_client_contact_12m.yml`](../../dbt/models/intermediate/int_client_contact_12m.yml)
- Window completeness: [`int_contact_window.sql`](../../dbt/models/intermediate/int_contact_window.sql);
  unit test `int_contact_window_needs_twelve_months_behind_the_week` in
  [`int_contact_window.yml`](../../dbt/models/intermediate/int_contact_window.yml)
- Roll-up: [`mart_advisor_weekly.sql`](../../dbt/models/marts/mart_advisor_weekly.sql),
  [`mart_org_weekly.sql`](../../dbt/models/marts/mart_org_weekly.sql),
  [`mart_portfolio_weekly.sql`](../../dbt/models/marts/mart_portfolio_weekly.sql)
- Quarterly stock: [`mart_org_quarterly.sql`](../../dbt/models/marts/mart_org_quarterly.sql)
- Checked against an independent Python reference ([`src/pulse/fixtures.py`](../../src/pulse/fixtures.py)):
  [`assert_mart_weekly_matches_fixture_exports.sql`](../../dbt/tests/assert_mart_weekly_matches_fixture_exports.sql),
  [`assert_portfolio_marts_match_fixture_exports.sql`](../../dbt/tests/assert_portfolio_marts_match_fixture_exports.sql)
- Fallback headline: [`src/pulse/narrative/facts.py`](../../src/pulse/narrative/facts.py),
  `test_the_lead_kpi_heads_the_narrative_once_it_has_a_value` in
  [`tests/narrative/test_narrative.py`](../../tests/narrative/test_narrative.py);
  [`web/src/data/kpi.ts`](../../web/src/data/kpi.ts), [`web/src/data/kpi.test.ts`](../../web/src/data/kpi.test.ts)
- Realistic spread on generated data: `test_default_scale_twelve_month_portfolio_contacted_spreads` in
  [`tests/generate/test_activity.py`](../../tests/generate/test_activity.py)
