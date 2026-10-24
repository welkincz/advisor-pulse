// Written by `make backtest` (src/pulse/quality/backtest_cli.py); do not edit by hand.
// The shipped flag rules scored against the generator's ground truth (ADR 0006).
export const FLAG_BACKTEST = {
  "tunedSeed": 20261013,
  "heldOutSeed": 424242,
  "rows": [
    {
      "rule": "ANOMALY",
      "level": "BRANCH",
      "stories": 17,
      "detected": 13,
      "recall": 0.765,
      "medianLagWeeks": 4,
      "precision": 0.013,
      "falsePer100": 17.37,
      "falsePer100Before": 69.56,
      "detectedBefore": 17
    },
    {
      "rule": "ANOMALY",
      "level": "DISTRICT",
      "stories": 2,
      "detected": 2,
      "recall": 1.0,
      "medianLagWeeks": 3.0,
      "precision": 0.031,
      "falsePer100": 15.76,
      "falsePer100Before": 73.64,
      "detectedBefore": 2
    },
    {
      "rule": "PRTF_MOVE",
      "level": "BRANCH",
      "stories": 26,
      "detected": 25,
      "recall": 0.962,
      "medianLagWeeks": 13,
      "precision": 0.133,
      "falsePer100": 6.09,
      "falsePer100Before": 2.84,
      "detectedBefore": 19
    }
  ]
} as const
