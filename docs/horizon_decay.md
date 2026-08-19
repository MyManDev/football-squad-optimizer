# Horizon Decay

- Contract: `horizon_decay_v1`
- Scaling rule: `linear_fixture_count_scaling_v1`
- Seasons: 2021-22, 2022-23, 2023-24, 2024-25 — 147 decision points
- Form window: 5

One projection is made at each decision point and scored against that gameweek and each of the next few, so what grows with the offset is the cost of acting on information that is one, two or three gameweeks old.

| Offset | Rows | Dropped | Bias | MAE | RMSE | MAE growth |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 101,447 | 0 | -0.0679 | 1.1340 | 2.2376 | +0.0% |
| 1 | 94,255 | 3,404 | -0.0628 | 1.1706 | 2.2806 | +3.2% |
| 2 | 90,807 | 3,748 | -0.0676 | 1.2014 | 2.3225 | +5.9% |
| 3 | 87,815 | 3,608 | -0.0693 | 1.2230 | 2.3473 | +7.8% |

## What the numbers say

Mean absolute error grows 7.8% from offset zero to offset 3 — roughly 2.6% per gameweek of horizon.

**The dropped counts matter as much as the errors.** A player who is not in the panel at the compared gameweek is dropped rather than scored, because a transfer or a delisting is an absence from the data and not a bad projection. That count grows with the offset, so the population behind each row is not the same population, and it is reported rather than left implicit.

## By fixture group

| Offset | blank | single | double_plus |
| ---: | ---: | ---: | ---: |
| 0 | — | 1.0956 (96,335) | 1.8586 (5,112) |
| 1 | 1.0000 (2) | 1.1323 (89,584) | 1.9059 (4,669) |
| 2 | 1.3333 (3) | 1.1560 (86,063) | 2.0256 (4,741) |
| 3 | 0.3333 (3) | 1.1777 (83,277) | 2.0565 (4,535) |

Mean absolute error with the row count behind it. A blank group of two or three rows is reported as it is and means nothing; it is left in rather than hidden so nobody reads its absence as a claim.

## Read against the planner measurements

`planner_doe` measured the planner against a myopic baseline and found horizon two worth +4.83 while horizon four cost -3.67. If that reversal were driven by the projection going stale, the decay above would have to be steep. It is not.

**That pointed in the right direction and stopped one step short.** `planner_horizon_seasons` then measured four seasons and 23 common windows per horizon: the +4.83 was one season, the four-season mean is -0.57, and no horizon beats myopic beyond noise. Horizon four loses -4.87, and the loss is a *selection* loss (-6.43) rather than a hit-cost one -- the planner pays fewer hits than myopic, 2.26 against 3.83 per window. It concentrates in windows with no calendar structure: -9.60 across ten plain windows against -1.23 across thirteen structured ones.

So "inside the planner" was the wrong place to look. Roster-level drift is small, as measured above, but a plan is not built from the roster -- it is built from the top of the ranking, and the top is where selection optimism is worst (-2.96 per selected starter). Weekly reprojection reshuffles that top as form regresses; a four-week plan stays committed to week one's ordering. The cost lands at the interface between the projection and the planner, not inside either.

Neither module is this side's to change, and neither of those measurements is mine. This one is recorded here because it is the claim this document got half right.

## Limits

This is not gate evidence for any prediction model, and it does not promote a horizon length. The frozen evaluation objective remains single-gameweek realized squad points. What a planner should do with this is a separate decision with its own owners.

The measurement uses the deterministic control, so it describes the drift of the projection that is actually shipped. A different model would have a different curve, and this one says nothing about it.

## Reproduction

```powershell
.venv\Scripts\python -m scripts.run_horizon_decay
```
