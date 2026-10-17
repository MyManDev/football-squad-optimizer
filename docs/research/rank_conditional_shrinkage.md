# Rank-conditional shrinkage of expected points before the squad decision

Record of the measurement pre-registered in [the protocol](rank_conditional_shrinkage_prereg.md). JSON twin: `rank_conditional_shrinkage.json`. Run at commit `edf99561` on a clean tree, 2026-10-17T12:27:27Z to 2026-10-17T12:49:09Z, on the Phase C v2 gradient-boosting out-of-fold table (`phase_c_control_components_gbm_v1`, table digest `eae3e9148509…`, roster `01d111138220…`, equal to the digests the protocol names). 2025-26 was read as development data under the v2 scope; it is not an unseen test. Measurement only, nothing promoted.

**Measured, not certified** under the pre-registered gate. Arm A (rank-conditional additive debias) minus the unshrunk control, paired on 176 folds: mean -0.847 points a gameweek, median +0.0, 90% season-aware moving-block interval [-1.591, -0.022], wins / ties / losses 51 / 63 / 62. The noise floor is 1.5 points a gameweek; certification needs the mean at or above it, the interval above zero and at most one negative season.

## The numbers that decide

| Quantity | Arm A minus control | Arm B minus control (reported, not gated) |
| --- | ---: | ---: |
| Paired folds | 176 | 176 |
| Mean difference, points a gameweek | -0.847 | +0.068 |
| Median difference | +0.0 | +0.0 |
| 90% interval | [-1.591, -0.022] | [-0.284, +0.562] |
| Wins / ties / losses | 51 / 63 / 62 | 16 / 143 / 17 |
| Mean realized score (control 61.903) | 61.057 | 61.972 |

| Season | Arm A minus control | Arm B minus control | Paired folds |
| --- | ---: | ---: | ---: |
| 2021-22 | -0.862 | +0.103 | 29 |
| 2022-23 | -1.611 | -0.417 | 36 |
| 2023-24 | +0.378 | +0.730 | 37 |
| 2024-25 | -0.405 | +0.432 | 37 |
| 2025-26 | -1.757 | -0.514 | 37 |

| Gate clause | Holds |
| --- | --- |
| Mean gain at or above +1.5 | False |
| 90% interval excludes zero | False |
| Negative seasons at most 1 (found 4) | False |

Population: 184 folds in the table, 8 burn-in, 176 targets (2021-22-gw10 to 2025-26-gw38), 0 excluded, 176 paired. No fold was excluded.

## Diagnostics, reported not gated

| Arm | Own projected minus realized, starters | Captain | Unshrunk projected minus realized, starters | Captain | Zero-minute starters | Autosub points | Vice recoveries | Proved / incumbent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| control | +0.505 | +0.415 | +0.505 | +0.415 | 120 | 433 | 11 | 176 / 0 |
| rank_debias | -0.079 | -0.527 | +0.477 | +0.373 | 116 | 319 | 10 | 176 / 0 |
| position_shrinkage | +0.301 | +0.011 | +0.506 | +0.340 | 119 | 441 | 10 | 176 / 0 |

| Arm | Shared of fifteen with control | Shared of eleven | Same captain rate |
| --- | ---: | ---: | ---: |
| rank_debias | 12.29 | 9.46 | 0.95 |
| position_shrinkage | 14.42 | 10.78 | 0.94 |

Mean bucket correction `r_b` over the target folds (Arm A): rank_001_005 -0.948, rank_006_015 -0.449, rank_016_030 -0.288, rank_031_060 -0.196, rank_061_120 -0.021, rank_121_plus +0.055. Mean position slope `lambda_pos` over the target folds (Arm B): GK 1.060, DEF 0.932, MID 0.952, FWD 0.918.

## What this is and is not

- One paired measurement of the single-gameweek squad decision: the same roster, prices, realized outcomes, solver limits (deterministic budget 5.0) and official autosub and captain scorer in every arm; only the `expected_points` column differs.
- The projection is the harness's own composition on the gradient-boosting v2 table; the fit of every target fold reads only the folds before it.
- Arm B is a shape control, reported and not gated.
- Not measured: transfer decisions and multi-week plans, the historical ridge control as an arm, any member's squad, Top100 evidence, 2025-26 as a test.
- Nothing is promoted and no product default changes. The verdict licenses nothing but this record.

## Reading (prose added after the run; every number above is the runner's)

The correction was built for the winner's curse that `selection_optimism.md` measured on the old
control: realized minus projected of -2.95 a selected starter and -3.86 for the captain. On the
gradient-boosting v2 table the control's own gap is +0.505 a starter and +0.415 for the captain,
so the composition of appearance probability and conditional points already carries little curse
at the top of the ranking, and the fitted top-bucket correction is -0.95 rather than -3.5. Arm A
does what it was fitted to do, its own projection of the selected starters is unbiased at -0.079,
but an additive shift that is constant inside a bucket changes the ranking only where two buckets
meet, and there it carries no information about which player is the better pick. The decisions it
changes score less, in four of five seasons. Arm B, the shape control, leaves the within-position
order unchanged, moves the decision rarely and reads as a tie with the control. The planning hit
cost of 8 on the live member path is not addressed by this result either way: it was not measured.

Two readings the owner's review of 2026-10-17 asked for are deferred rather than added here,
because the protocol was frozen before the run and is not widened after it: the season chain
with transfers under the planning hit cost at 4, with and without the transfer cap, and buckets
by the four position groups rather than six pooled across positions. Both go to the named
follow-up pre-registration `docs/research/rank_conditional_shrinkage_chain_prereg.md`, not
written yet, and the protocol's "What is not measured" section says so in a scope statement the
owner asked for. On the scheduling of this run: the three arms were solved in three threads, and
the claim that the numbers do not depend on the scheduling holds only while the 600 second
wall-clock cap never binds; every one of the 528 solves ended OPTIMAL inside the deterministic
budget of 5.0, so the cap did not bind here. The per-fold artifact carries solver statuses, not
wall times, so no largest wall time is quoted. The commits after the run (c6cc973d and the one
that adds this paragraph) changed documents and the runner's harness note only; the record's
`repository_commit` stays `edf99561` and no number moved.

Per-fold table: `artifacts/rank_conditional_shrinkage/rank_conditional_shrinkage_folds.csv` (sha256 `5703db92252ba5242c68e6287496a9c8efcd7e924db3b4edbb66f04aeb4a2edf`).
