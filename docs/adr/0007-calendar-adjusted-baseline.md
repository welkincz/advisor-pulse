# ADR 0007 — Calendar-adjusted anomaly baseline

- Status: Accepted (2026-11-11, owner approved). The calendar-adjusted rule ships in `mart_weekly_report`.
- Date: 2026-11-05
- Issue: #332 (from #300, ADR 0006)

## Context

ADR 0006 found that most national anomaly false alarms fall in or just after calendar weeks. DQ031 already divides weekly volume by the business calendar's expectation, but the report's anomaly flag does not. A holiday week looks abnormal, and then sits in the next 13 baselines and widens them.

## What was tried

`Thresholds(calendar_adjusted=True)` changes one rule, in the backtest only. For the four KPIs that scale with working days (activities per advisor, outbound calls, appointments booked, clients contacted), the `ANOMALY` rule compares `value / week_factor` with the 13 weeks before it, adjusted the same way. Rates, averages, `PRTF_MOVE`, UP and DOWN are unchanged, and `z` stays at 3. `mart_weekly_report` is not changed, and the check that the backtest reproduces the mart still runs at the shipped rule.

## Results

Two full histories, 2024-W41 to 2026-W42, default scale, built from `229dd7e`. Nothing was tuned on either seed, so both are out-of-sample for this candidate. Every rule and level is in [the results](0007-calendar-baseline-results.json). Each cell is shipped → adjusted.

| Level | Seed | Stories caught | Median lag (wk) | Precision | False / 100 node-weeks | False alarms in calendar weeks |
|---|---|---|---|---|---|---|
| National | 20261013 | none to catch | – | 0.0% → 0.0% | 29.25 → 13.21 | 23 → 5 |
| National | 424242 | none to catch | – | 0.0% → 21.4% | 26.42 → 10.38 | 22 → 4 |
| Region | 20261013 | 1/1 → 1/1 | 2 → 1 | 1.6% → 3.2% | 17.64 → 14.15 | 99 → 49 |
| Region | 424242 | 1/1 → 1/1 | 5 → 3 | 1.6% → 4.1% | 16.89 → 13.21 | 87 → 30 |
| District | 20261013 | 2/2 → 2/2 | 1 → 1 | 4.9% → 8.3% | 16.26 → 12.82 | 145 → 60 |
| District | 424242 | 2/2 → 2/2 | 3 → 1.5 | 3.1% → 6.3% | 15.65 → 13.26 | 134 → 54 |
| Branch | 20261013 | 17/17 → 16/17 | 2 → 2.5 | 1.7% → 2.2% | 17.48 → 17.00 | 551 → 408 |
| Branch | 424242 | 13/17 → 13/17 | 4 → 3 | 1.3% → 1.4% | 17.34 → 17.38 | 492 → 364 |

- **National, region and district improve on both seeds.** National false alarms more than halve, and no story above branch level is lost. Lags are equal or shorter.
- **The changed districts are still caught,** and on the held-out seed about twice as fast (3 → 1.5 weeks).
- **Branches barely change.** Calendar false alarms fall by about a quarter, but the total stays flat: clean baselines are tighter, so other weeks now cross 3σ. One seed loses one of 17 branch stories. The other's lag improves.
- **Precision stays low.** Better is not good: at district level about 92 flags in 100 still match no story.

## Limits

- **The factors are the generator's own.** `week_factor` is exactly how the generator scales volume, so this is the best case. A real bank would estimate the factors and do worse.
- **Clients contacted is not strictly proportional to working days.** It is adjusted the same way as a simplification.
- **Synthetic stories only,** as in ADR 0006.

## Recommendation

Ship it, because it removes false alarms that a manager can do nothing about, at no cost above branch level. Shipping means a week factor in `dim_date` for `mart_weekly_report`, keeping the backtest's check that it reproduces the mart, re-pinning `test_backtest_minimums.py`, and rewriting the `/quality` table. That is a PLAN.md §7 change, so it is the owner's call.

## Decision

Accepted by the owner on 2026-11-11. What shipped:

- **One calendar.** `make seeds` writes `pulse.business_calendar.week_factor` for every ISO week in `dim_date`'s default range to the `business_week` seed, and `dim_date.week_factor` joins it (not null, tested). The generator, DQ031 and the report now read the same factors; `make seeds-check` fails if the seed drifts from the Python calendar.
- **The mart.** `mart_weekly_report` divides `ACT_PER_ADV`, `CALLS_OUT`, `APPT_BOOKED` and `CLIENTS_CONTACTED` by the week factor before the `ANOMALY` test, in the week and its 13-week baseline. Values, `trailing_13w_avg`, `UP`/`DOWN` and the other KPIs are unchanged. A dbt unit test holds a holiday week that the raw rule would flag.
- **The backtest.** `SHIPPED` is the adjusted rule, and the check that the backtest reproduces the mart runs at it. `--raw` scores the previous rule for comparison.
- **Rebuilt evidence.** Both seeds rebuilt from this branch: the backtest reproduces the mart row for row, and every adjusted score in the table above is reproduced except national, where both rules raise two fewer false alarms per seed than the `229dd7e` build (adjusted national 11.32 and 8.49 per 100 node-weeks). `test_backtest_minimums.py` is re-pinned to the adjusted rule and `/quality` shows its held-out results.

## How to reproduce

Build each seed as in ADR 0006, without `R2_*` set (10.6 minutes each on an Apple M4 Max), then:

```bash
make backtest BACKTEST_DIRS="/tmp/pulse-20261013/data /tmp/pulse-424242/data" ARGS="--raw --json out.json"
```
