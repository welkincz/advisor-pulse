# #309 visual and acceptance evidence

Cropped narrative sections at 1440 px and 375 px viewports, light/dark, reduced motion. Synthetic fixture scenario: the recorded ON model cites 59 outbound calls; the current report has 79, with its change recalculated from the prior 61. The original text stays, alongside the notice, marker and current figures. Shared fixtures were not modified. The browser also verified native-details keyboard activation and no sideways overflow at 375 px.

| Viewport/theme | Before | After |
|---|---|---|
| 1440 light | [Before](before-1440-light.png) | [After](after-1440-light.png) |
| 1440 dark | [Before](before-1440-dark.png) | [After](after-1440-dark.png) |
| 375 light | [Before](before-375-light.png) | [After](after-375-light.png) |
| 375 dark | [Before](before-375-dark.png) | [After](after-375-dark.png) |

Downloaded full export: weekly run `40364746899`, latest `2026-W43`. Rebuilt templates only in an isolated local copy; `make web-audit-latest EXPORTS=data/309-full-export WEEK=2026-W41` checked **1972 figures, 0 disagreements**. A second full-export copy, with a synthetic past AB model citing 759 calls against the current 760, also passed **1920/1920**, exercising the marked-restatement path without model calls. A negative control hid the notice and the actual audit recorded “restated fact must be disclosed”.

On Apple M4 Max / Python 3.12.11, three fresh narrative directories each built all **26 weeks × 27 nodes = 702 templates**, including warehouse loading and JSON writes: **0.515, 0.541, 0.553 seconds**. Refreshing the mixed downloaded history took **0.509 seconds** and left the existing model file (`2026-W43.json`) byte-identical. These are local timings, with no provider calls. The 26-week boundary, mixed-file model retention and corrupt-file failure behavior have Python regressions.
