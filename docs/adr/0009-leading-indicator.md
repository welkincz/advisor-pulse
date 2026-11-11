# ADR 0009 — A leading indicator of portfolio coverage slipping

- Status: Accepted. The owner approved shipping the measure and its contract change on 2026-11-11.
- Date: 2026-11-05
- Issue: #302

## Context

A 12-month rate lags by construction: a branch can stop contacting half its book and the headline barely moves for months. This asks which signal warns earliest, judged on data the fit never saw.

## Method

`scripts/leading_indicator.py` builds a branch-week panel from the warehouse. Every signal is known at week t.

- **Target:** the branch's rate falls by at least X points by t+13. X = 0.5 is about 21% of branch-weeks; X = 1 is about 12%.
- **Candidates:** the share of the book with no contact in 9+ months; median days since last contact; top-decile share of contacts; the 13-week change in each; and the 13-week fall in unique clients contacted.
- **Baseline:** the rate's own fall over the previous 13 weeks.
- **Judge:** each cut maximizes F1 on seed 20261013 up to 2026-W05, then is scored unchanged on that seed's later weeks and on seed 424242.
- **Lead:** per branch, the weeks from the signal's first correct flag until the baseline flags that branch too, capped at 13.

## Results

The baseline and the best signal, on the held-out seed. [Every signal and sample at 0.5 points](0009-leading-indicator-results.json); [at 1 point](0009-leading-indicator-results-1pt.json).

| Target | Signal | Flags | Precision | Recall | F1 | AUC | Median lead (wk) |
|---|---|--:|--:|--:|--:|--:|--:|
| Falls ≥ 0.5 pt | Rate's own 13-week fall | 4,386 | 31.6% | 67.8% | 0.431 | 0.700 | 0 |
| Falls ≥ 0.5 pt | **Rise in 9-month-stale share** | 2,279 | 52.0% | 58.1% | 0.549 | 0.834 | 0 |
| Falls ≥ 1 pt | Rate's own 13-week fall | 2,304 | 22.7% | 49.0% | 0.311 | 0.729 | 0 |
| Falls ≥ 1 pt | **Rise in 9-month-stale share** | 858 | 56.9% | 45.6% | 0.506 | 0.867 | 3 |

- **The 13-week rise in the 9-month-stale share beats the baseline in both held-out samples, at both targets:** AUC 0.83–0.87 against 0.70–0.73 on the held-out seed, and 0.87–0.91 against 0.75–0.79 on the tuning seed's later weeks. On the held-out seed it raises half as many flags at about twice the precision.
- **The earliest warning is modest.** Against a 1-point fall it leads the rate's trend by a median of 3 weeks. Against 0.5 points the median lead is 0, because the fitted baseline cut is so loose it flags 45% of branch-weeks. The gain is mostly precision. It tells you which falling trends are real. Signals with a longer median lead exist, such as median days since contact (5 weeks at 1 point), but their precision is low: 19.4% with 3,404 flags, below even the baseline's 22.7%. Four in five of their warnings would be false. A small, early lead on a precise signal is worth more than a long lead on a noisy one.
- **The level of the stale share is weak** (AUC 0.59); the change is what predicts. Contact concentration, the idea the generator is built on, is close to useless as a level at branch level (AUC 0.52).
- **Part of this is arithmetic, and that is the point.** A client last contacted 9 months ago falls out of the window within 3 months unless someone calls. The signal reads that queue directly, so it should work on real data too, unlike a tuned threshold.

## Limits

- Consecutive branch-weeks overlap, so the counts overstate the independent evidence.
- Bank-wide outreach improves over these years, which affects how often a branch falls.
- Recall is about half: many falls are noise around 0.5 to 1 point that no signal should catch.
- Synthetic data. The generator's drift is one mechanism out of many a real bank would have.

## Recommendation

Add **stale share (9+ months)** and its 13-week change as a secondary measure at branch level, and describe it as "more of this book is about to fall out of the window". Don't present it as a forecast or add it to the flag rule.

## Decision

Shipped as `stale_9m_share` and `stale_9m_rise_13w` on the branch rows of `mart_org_weekly` (PLAN.md §6.8, §7), shown as one line under a branch's measures on the drill page. It has no KPI code, so it stays out of the weekly report, its flags and the narrative. `tests/integration/test_stale_book.py` checks that the mart and this script agree on every branch-week the script scores.

## How to reproduce

The two warehouses are the full histories from ADR 0006: 2024-W41 to 2026-W42 at default scale, one per seed. Seed 20261013 (the project default) is the tuning seed; 424242 is held out. Use scratch directories and never set `R2_*`. Each seed takes about 4 minutes to generate and 45 minutes for the catch-up run on an Apple M4 Max.

```bash
for seed in 20261013 424242; do
  export PULSE_SEED=$seed PULSE_DATA_DIR=/tmp/pulse-$seed/data PULSE_EXPORT_DIR=/tmp/pulse-$seed/export
  uv run pulse generate --backfill --from 2024-W41 --to 2026-W42
  uv run pulse run --week 2026-W42 --run-type backfill    # one run loads every week
done
unset PULSE_SEED PULSE_DATA_DIR PULSE_EXPORT_DIR
uv run python scripts/leading_indicator.py /tmp/pulse-20261013/data /tmp/pulse-424242/data --json docs/adr/0009-leading-indicator-results.json
uv run python scripts/leading_indicator.py /tmp/pulse-20261013/data /tmp/pulse-424242/data --fall 1.0 --json docs/adr/0009-leading-indicator-results-1pt.json
```

`uv run pulse backfill --from 2024-W41 --to 2026-W42 --rebuild` with the same variables builds the same marts (#342). That span gives 106 reported weeks at 122 branches. A branch-week needs a reported week 13 weeks before and 13 weeks after, which leaves 80 scored weeks: 56 tuning weeks (2025-W02 to 2026-W05, 6,832 rows), 24 later weeks (2026-W06 to 2026-W29, 2,928 rows) and 9,760 rows on the held-out seed.
