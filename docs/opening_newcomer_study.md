# Opening projection: newcomers, movers, and what the deadline publishes

- Contract `opening_newcomer_study_v1`; fitted on 2020-21, 2021-22, 2022-23, 2023-24, 2024-25, judged walk-forward on 2022-23, 2023-24, 2024-25; 2000 paired bootstrap resamples, seed 0.
- Measurement only. The locked 2025-26 holdout was not read, no contract or model changed, and the verdict below was computed by `gate_verdict`, not written by hand.

## The population the model cannot see

| Season | Opening rows | Newcomers | Share | Movers | Newcomers who did not play |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021-22 | 554 | 218 | 39% | 18 | 67% |
| 2022-23 | 573 | 202 | 35% | 27 | 64% |
| 2023-24 | 658 | 253 | 38% | 31 | 72% |
| 2024-25 | 616 | 201 | 33% | 39 | 72% |

## What ships today

`expected_points = 0.29941 x price` for every player without a record. Over 874 such players it predicts 1.387 points where 0.686 were scored — a bias of **+0.701** and a mean absolute error of 1.364. The coefficient was fitted on every opening player, and most players have a record and play; a newcomer usually does not.

## Candidates, walk-forward

| Candidate | Pooled MAE gain | 90% interval | Per-season gain | Rank (candidate vs control) |
| --- | ---: | --- | --- | --- |
| `M1_price_by_position` | +0.333 | [+0.308, +0.356] | +0.261 / +0.322 / +0.417 | 0.52v0.52 / 0.47v0.47 / 0.51v0.51 |
| `M2_ownership` | +0.363 | [+0.332, +0.393] | +0.259 / +0.372 / +0.457 | 0.48v0.52 / 0.36v0.47 / 0.43v0.51 |
| `M3_source_expectation` | +0.401 | [+0.365, +0.435] | +0.269 / +0.434 / +0.492 | 0.36v0.52 / 0.32v0.47 / 0.35v0.51 |
| `M4a_published_difficulty` | +0.394 | [+0.357, +0.429] | +0.247 / +0.430 / +0.497 | 0.31v0.52 / 0.30v0.47 / 0.38v0.51 |
| `M4b_carried_team_strength` | +0.389 | [+0.349, +0.427] | +0.232 / +0.427 / +0.498 | 0.24v0.52 / 0.28v0.47 / 0.37v0.51 |

Ordering restricted to the newcomers who actually played (a diagnostic, not part of the gate):

| Candidate | Rank among players, by season | Control |
| --- | --- | --- |
| `M1_price_by_position` | 0.169 / 0.220 / 0.293 | 0.169 / 0.220 / 0.293 |
| `M2_ownership` | 0.138 / 0.043 / 0.187 | 0.169 / 0.220 / 0.293 |
| `M3_source_expectation` | 0.116 / 0.123 / 0.123 | 0.169 / 0.220 / 0.293 |
| `M4a_published_difficulty` | -0.090 / 0.221 / 0.133 | 0.169 / 0.220 / 0.293 |
| `M4b_carried_team_strength` | 0.115 / 0.124 / 0.139 | 0.169 / 0.220 / 0.293 |

## What the squad would have been

| Candidate | Realized difference by season | Newcomers started |
| --- | --- | --- |
| `M1_price_by_position` | +0 / +0 / +0 | 0 vs 0 / 0 vs 0 / 0 vs 0 |
| `M2_ownership` | +12 / +0 / +0 | 2 vs 0 / 0 vs 0 / 0 vs 0 |
| `M3_source_expectation` | +12 / +0 / +7 | 2 vs 0 / 0 vs 0 / 0 vs 0 |
| `M4a_published_difficulty` | +8 / +0 / +0 | 2 vs 0 / 0 vs 0 / 0 vs 0 |
| `M4b_carried_team_strength` | +8 / +0 / +0 | 3 vs 0 / 0 vs 0 / 0 vs 0 |

## Movers

- 115 players changed clubs across the studied openings. Their carried projection is biased -0.512 against -0.332 for players who stayed; mean absolute error 1.616 against 1.794.
- Per season the mover bias is 2021-22 -1.326, 2022-23 -0.652, 2023-24 +0.239, 2024-25 -0.635 — the sign is not stable.
- The best shrink toward the price prior is **0.00** (1.425 against 1.577 unshrunk), and it does not improve every evaluated season.

## Verdict

| Candidate | Accuracy | Ordering | Decision | Passes |
| --- | --- | --- | --- | --- |
| `M1_price_by_position` | pass | fail | pass (+0.0 points, 0 loss) | no |
| `M2_ownership` | pass | fail | pass (+4.0 points, 0 loss) | no |
| `M3_source_expectation` | pass | fail | pass (+6.3 points, 0 loss) | no |
| `M4a_published_difficulty` | pass | fail | pass (+2.7 points, 0 loss) | no |
| `M4b_carried_team_strength` | pass | fail | pass (+2.7 points, 0 loss) | no |

**No candidate clears the gate**, so nothing is proposed for promotion and the opening gameweek runs on the control.
