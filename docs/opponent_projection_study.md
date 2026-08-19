# An opponent-aware adjustment, measured where the decision is made

- Contract `opponent_projection_study_v1`; the control is `deterministic_baseline_control` on its own walk-forward folds over 2021-22, 2022-23, 2023-24, 2024-25, judged on 2022-23, 2023-24, 2024-25.
- The adjustment is fitted per position on the residuals of earlier seasons only: attackers scale with the goals the rating expects their club to score, goalkeepers and defenders with the clean-sheet probability it implies, both per fixture so the calendar is not counted twice.
- Intervals are bootstrapped over **folds**, not players (2000 resamples, seed 0).
- Measurement only. The locked 2025-26 holdout is refused, nothing under `prediction/` changed, and the verdict was computed by `gate_verdict`.

## Population

| Season | Folds | Rows | Mean predicted | Mean realized |
| --- | ---: | ---: | ---: | ---: |
| 2021-22 | 37 | 22676 | 1.351 | 1.347 |
| 2022-23 | 36 | 24384 | 1.277 | 1.269 |
| 2023-24 | 37 | 28084 | 1.085 | 1.085 |
| 2024-25 | 37 | 26303 | 1.168 | 1.159 |

## Candidates

| Candidate | Folds | Error improvement | 90% interval | Ordering | Decision (points/fold) | 90% interval |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| `R_team_rating` | 110 | +0.0016 | [+0.0011, +0.0021] | -0.0003 | -0.909 | [-1.909, +0.164] |
| `P_published_rating` | 110 | +0.0121 | [+0.0100, +0.0143] | +0.0021 | +1.736 | [+0.518, +3.027] |

### Per season

| Candidate | Season | Error | Ordering | Decision |
| --- | --- | ---: | ---: | ---: |
| `R_team_rating` | 2022-23 | +0.0009 | -0.0002 | -1.500 |
| `R_team_rating` | 2023-24 | +0.0023 | -0.0002 | -1.432 |
| `R_team_rating` | 2024-25 | +0.0017 | -0.0004 | +0.189 |
| `P_published_rating` | 2022-23 | +0.0085 | +0.0021 | +1.111 |
| `P_published_rating` | 2023-24 | +0.0086 | +0.0025 | +2.216 |
| `P_published_rating` | 2024-25 | +0.0192 | +0.0016 | +1.865 |

### Fitted coefficients and the multipliers they produce

| Candidate | Position | Slope | Centre | Mean multiplier | Range |
| --- | --- | ---: | ---: | ---: | --- |
| `R_team_rating` | GK | +0.2624 | +0.2725 | 0.9956 | [0.739, 1.124] |
| `R_team_rating` | DEF | +0.2276 | +0.2717 | 0.9956 | [0.739, 1.124] |
| `R_team_rating` | MID | -0.0406 | +1.4202 | 0.9956 | [0.739, 1.124] |
| `R_team_rating` | FWD | -0.0418 | +1.3326 | 0.9956 | [0.739, 1.124] |
| `P_published_rating` | GK | +0.1008 | -2.8167 | 0.9903 | [0.599, 1.311] |
| `P_published_rating` | DEF | +0.1712 | -2.8167 | 0.9903 | [0.599, 1.311] |
| `P_published_rating` | MID | +0.0735 | -2.8192 | 0.9903 | [0.599, 1.311] |
| `P_published_rating` | FWD | +0.0727 | -2.8343 | 0.9903 | [0.599, 1.311] |

## Verdict

The gate: more accurate pooled over folds with the fold-level interval clear of zero and the sign holding every season; an ordering that does not get worse; and a squad that scores more, with its own fold-level interval clear of zero.

- `R_team_rating`: fails (accuracy: True; ordering: False; decision: False; -0.909 realized points per fold over 110 folds).
- `P_published_rating`: passes (accuracy: True; ordering: True; decision: True; +1.736 realized points per fold over 110 folds).

## Is the published rating admissible?

The archive stores one difficulty value per club per venue per season, constant across the season, so it cannot encode fixture-level hindsight. Whether it encodes *season-level* hindsight is testable: a rating set before a season should track the previous season's table more closely than the coming one's.

| Season | Correlation with this season's table | With the previous season's |
| --- | ---: | ---: |
| 2022-23 | +0.731 | +0.850 |
| 2023-24 | +0.894 | +0.845 |
| 2024-25 | +0.940 | +0.372 |

Flagged: 2023-24, 2024-25 — the rating tracks its own season better than the one before it, so at least part of what it knows was not knowable at the deadlines it is used at.


A candidate cleared the gate but is **not** carried forward: its signal failed the hindsight check (`published_difficulty_hindsight`).

