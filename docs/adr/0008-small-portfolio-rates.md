# ADR 0008 — Honest rates for small portfolios: intervals yes, shrinkage no

- Status: Proposed. Nothing ships until the owner decides.
- Date: 2026-11-05
- Issue: #301

## Context

#301 assumed that small books swing by chance and top and bottom the rankings, so rankings should use an empirical-Bayes shrunk rate, shown beside a Wilson interval. Its outside judge asks whether shrinkage ranks closer to the generator's truth, on two seeds.

## What was measured

`scripts/shrinkage_eval.py` fits a beta prior by the method of moments per week and level, and compares the raw and shrunk rates with the truth: each advisor's seeded contact concentration, client-weighted for branches. A test confirms the evaluation does find a gain when books are small and uneven, so a flat result is a real finding.

## Results

[All 12 rows](0008-shrinkage-results.json); 2026-W42 shown here, the other two weeks agree.

| Seed | Level | Median clients | Kappa | Median move (pt) | Wilson ± (pt) | Spearman raw → shrunk | Bottom decile raw → shrunk |
|---|---|--:|--:|--:|--:|---|---|
| 20261013 | Advisor | 196 | 11.5 | 0.42 | 4.26 | 0.752 → 0.759 | 46% → 46% |
| 20261013 | Branch | 1,216 | 41.2 | 0.12 | 1.86 | 0.594 → 0.594 | 58% → 58% |
| 424242 | Advisor | 189 | 13.2 | 0.48 | 4.21 | 0.746 → 0.753 | 45% → 45% |
| 424242 | Branch | 1,207 | 39.0 | 0.12 | 1.82 | 0.588 → 0.587 | 50% → 50% |

- **Shrinkage does almost nothing here.** Across all 12 rows, Spearman moves by +0.004 to +0.007 for advisors and by at most ±0.001 for branches. The bottom decile moves by at most 2 points. The prior is weak (kappa 12 to 47 clients) against books of about 190 and 1,200.
- **The premise doesn't hold in this data.** The smallest branch has 1,065 clients, and advisors differ far more than sampling noise explains.
- **Intervals do say something.** A branch's rate is good to about ±1.9 points and an advisor's to about ±4.3. Those are wider than many week-on-week moves and many rank gaps.

## Recommendation

- **Don't ship the shrunk rate.** It would add columns, a second rate to explain and a ranking that no longer sorts by the number on the screen, for a gain too small to see.
- **Do ship the Wilson interval, with no contract change.** The exports already hold the numerator and denominator at advisor, portfolio and org level, so the site can compute the interval where it is shown. A hover card would read "84.2%, likely 83.1–85.3%".
- **Revisit if books get small.** Rerun the evaluation first.

The issue's acceptance asks for new mart columns and shrunk rankings. This recommendation drops them, so it is the owner's decision. The hover-card work waits for it, and #301 stays open until then.

## Limits

The truth is a proxy: concentration sets how much of a book hears from an advisor, but client mix also matters, so neither rate can reach a Spearman of 1. Real books may be far more uneven than these, which is why the evaluation is kept.

## How to reproduce

```bash
uv run python scripts/shrinkage_eval.py /tmp/pulse-20261013/data /tmp/pulse-424242/data --json out.json
```
