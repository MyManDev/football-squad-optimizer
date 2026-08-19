# Schedule signal: does a five-week window know more than a flat projection?

- Contract `schedule_signal_study_v1`; fitted on 2020-21, 2021-22, 2022-23, 2023-24, 2024-25, judged walk-forward on 2022-23, 2023-24, 2024-25.
- Windows of 5 gameweeks opening at 6, 11, 16, 21, 26, 31; a player enters a window with at least 180 minutes in the 5 gameweeks before it.
- 2000 paired bootstrap resamples, seed 0; the transfer check charges 4 points.
- Measurement only. The locked 2025-26 holdout is refused by the configuration, no model or contract changed, and the verdict below was computed by `gate_verdict`.

## Population

| Season | Rows | Windows | Mean fixtures in window | Blank | Mean realized |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2020-21 | 1491 | 6 | 5.07 | 0.0% | 12.82 |
| 2021-22 | 1457 | 6 | 4.85 | 0.0% | 12.02 |
| 2022-23 | 1450 | 6 | 4.95 | 0.0% | 12.59 |
| 2023-24 | 1455 | 6 | 4.95 | 0.0% | 11.98 |
| 2024-25 | 1498 | 6 | 5.00 | 0.0% | 12.40 |

## Rules

| Rule | Rows | Mean absolute error | Rank correlation |
| --- | ---: | ---: | ---: |
| `A_flat` | 4403 | 7.0496 | 0.2773 |
| `B_calendar` | 4403 | 6.9359 | 0.3113 |
| `C_published_difficulty` | 4403 | 6.9097 | 0.3157 |
| `D_carried_strength` | 4403 | 6.9417 | 0.3188 |

## Comparisons

| Rule | Against | Rows | Error improvement | 90% interval | Rank improvement |
| --- | --- | ---: | ---: | --- | ---: |
| `B_calendar` | `A_flat` | 4403 | +0.1137 | [+0.0779, +0.1507] | +0.0340 |
| `C_published_difficulty` | `B_calendar` | 4403 | +0.0261 | [+0.0070, +0.0441] | +0.0044 |
| `D_carried_strength` | `B_calendar` | 4403 | -0.0059 | [-0.0281, +0.0144] | +0.0075 |

### Per season

| Rule | Against | Season | Error | Ordering |
| --- | --- | --- | ---: | ---: |
| `B_calendar` | `A_flat` | 2022-23 | +0.1939 | +0.0541 |
| `B_calendar` | `A_flat` | 2023-24 | +0.1393 | +0.0353 |
| `B_calendar` | `A_flat` | 2024-25 | +0.0112 | +0.0127 |
| `C_published_difficulty` | `B_calendar` | 2022-23 | -0.0355 | -0.0016 |
| `C_published_difficulty` | `B_calendar` | 2023-24 | +0.0380 | +0.0028 |
| `C_published_difficulty` | `B_calendar` | 2024-25 | +0.0743 | +0.0119 |
| `D_carried_strength` | `B_calendar` | 2022-23 | -0.1001 | +0.0053 |
| `D_carried_strength` | `B_calendar` | 2023-24 | +0.0332 | +0.0037 |
| `D_carried_strength` | `B_calendar` | 2024-25 | +0.0475 | +0.0134 |

## Decisions

| Rule | Against | Season | Origin | Squad difference | Changed starters | Transfer net |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `B_calendar` | `A_flat` | 2022-23 | 6 | +14.00 | 4 | +3.00 |
| `B_calendar` | `A_flat` | 2022-23 | 11 | +8.00 | 1 | no move |
| `B_calendar` | `A_flat` | 2022-23 | 16 | +52.00 | 5 | +3.00 |
| `B_calendar` | `A_flat` | 2022-23 | 21 | +56.00 | 3 | +10.00 |
| `B_calendar` | `A_flat` | 2022-23 | 26 | +20.00 | 4 | -19.00 |
| `B_calendar` | `A_flat` | 2022-23 | 31 | +42.00 | 1 | no move |
| `B_calendar` | `A_flat` | 2023-24 | 6 | +0.00 | 0 | no move |
| `B_calendar` | `A_flat` | 2023-24 | 11 | +0.00 | 0 | no move |
| `B_calendar` | `A_flat` | 2023-24 | 16 | +0.00 | 0 | no move |
| `B_calendar` | `A_flat` | 2023-24 | 21 | +13.00 | 1 | +9.00 |
| `B_calendar` | `A_flat` | 2023-24 | 26 | +15.00 | 4 | -4.00 |
| `B_calendar` | `A_flat` | 2023-24 | 31 | +7.00 | 2 | -8.00 |
| `B_calendar` | `A_flat` | 2024-25 | 6 | +0.00 | 0 | no move |
| `B_calendar` | `A_flat` | 2024-25 | 11 | +0.00 | 0 | no move |
| `B_calendar` | `A_flat` | 2024-25 | 16 | +0.00 | 0 | no move |
| `B_calendar` | `A_flat` | 2024-25 | 21 | +38.00 | 3 | +2.00 |
| `B_calendar` | `A_flat` | 2024-25 | 26 | -16.00 | 2 | +0.00 |
| `B_calendar` | `A_flat` | 2024-25 | 31 | +16.00 | 2 | +4.00 |
| `C_published_difficulty` | `B_calendar` | 2022-23 | 6 | +9.00 | 3 | +18.00 |
| `C_published_difficulty` | `B_calendar` | 2022-23 | 11 | -4.00 | 0 | no move |
| `C_published_difficulty` | `B_calendar` | 2022-23 | 16 | +0.00 | 0 | no move |
| `C_published_difficulty` | `B_calendar` | 2022-23 | 21 | +0.00 | 0 | no move |
| `C_published_difficulty` | `B_calendar` | 2022-23 | 26 | -28.00 | 3 | -12.00 |
| `C_published_difficulty` | `B_calendar` | 2022-23 | 31 | -13.00 | 1 | -17.00 |
| `C_published_difficulty` | `B_calendar` | 2023-24 | 6 | -9.00 | 1 | -13.00 |
| `C_published_difficulty` | `B_calendar` | 2023-24 | 11 | +0.00 | 0 | no move |
| `C_published_difficulty` | `B_calendar` | 2023-24 | 16 | +14.00 | 1 | +10.00 |
| `C_published_difficulty` | `B_calendar` | 2023-24 | 21 | -18.00 | 1 | no move |
| `C_published_difficulty` | `B_calendar` | 2023-24 | 26 | -21.00 | 2 | -33.00 |
| `C_published_difficulty` | `B_calendar` | 2023-24 | 31 | +23.00 | 1 | no move |
| `C_published_difficulty` | `B_calendar` | 2024-25 | 6 | +14.00 | 1 | no move |
| `C_published_difficulty` | `B_calendar` | 2024-25 | 11 | -11.00 | 4 | -3.00 |
| `C_published_difficulty` | `B_calendar` | 2024-25 | 16 | +7.00 | 4 | -33.00 |
| `C_published_difficulty` | `B_calendar` | 2024-25 | 21 | +0.00 | 1 | +3.00 |
| `C_published_difficulty` | `B_calendar` | 2024-25 | 26 | +0.00 | 0 | no move |
| `C_published_difficulty` | `B_calendar` | 2024-25 | 31 | -9.00 | 2 | -5.00 |
| `D_carried_strength` | `B_calendar` | 2022-23 | 6 | +0.00 | 0 | no move |
| `D_carried_strength` | `B_calendar` | 2022-23 | 11 | -8.00 | 1 | -8.00 |
| `D_carried_strength` | `B_calendar` | 2022-23 | 16 | +7.00 | 1 | no move |
| `D_carried_strength` | `B_calendar` | 2022-23 | 21 | +0.00 | 0 | no move |
| `D_carried_strength` | `B_calendar` | 2022-23 | 26 | -37.00 | 3 | -12.00 |
| `D_carried_strength` | `B_calendar` | 2022-23 | 31 | -25.00 | 3 | -10.00 |
| `D_carried_strength` | `B_calendar` | 2023-24 | 6 | +13.00 | 1 | +9.00 |
| `D_carried_strength` | `B_calendar` | 2023-24 | 11 | +7.00 | 2 | +15.00 |
| `D_carried_strength` | `B_calendar` | 2023-24 | 16 | +3.00 | 1 | no move |
| `D_carried_strength` | `B_calendar` | 2023-24 | 21 | +0.00 | 0 | no move |
| `D_carried_strength` | `B_calendar` | 2023-24 | 26 | +0.00 | 0 | no move |
| `D_carried_strength` | `B_calendar` | 2023-24 | 31 | +20.00 | 1 | no move |
| `D_carried_strength` | `B_calendar` | 2024-25 | 6 | +8.00 | 2 | no move |
| `D_carried_strength` | `B_calendar` | 2024-25 | 11 | -4.00 | 3 | +15.00 |
| `D_carried_strength` | `B_calendar` | 2024-25 | 16 | +20.00 | 4 | -33.00 |
| `D_carried_strength` | `B_calendar` | 2024-25 | 21 | +0.00 | 1 | no move |
| `D_carried_strength` | `B_calendar` | 2024-25 | 26 | +0.00 | 0 | no move |
| `D_carried_strength` | `B_calendar` | 2024-25 | 31 | -16.00 | 2 | no move |

## Verdict

The gate: the paired interval clears zero, the sign holds in every judged season, the ordering does not get worse, and the decision check is not negative once a transfer is charged for.

- **Schedule over a flat projection** (`B_calendar` vs `A_flat`): passes (interval clears zero: True; sign consistent: True; ordering not worse: True; decision: True).
- **Difficulty over the calendar** (`C_published_difficulty`): fails (interval clears zero: True; sign consistent: False; ordering not worse: True; decision: False; mean squad difference -2.556; mean transfer net -8.500 over 10 proposed moves).
- **Difficulty over the calendar** (`D_carried_strength`): fails (interval clears zero: False; sign consistent: False; ordering not worse: True; decision: False; mean squad difference -0.667; mean transfer net -3.429 over 7 proposed moves).

No difficulty rule cleared the gate.

