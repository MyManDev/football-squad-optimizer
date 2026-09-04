# Opponent Strength — signal the control leaves on the table

- Contract: `opponent_strength_signal_v1`
- Strength window: 6 matches, shifted
- Population: 101,447 rows over 147 folds, 2021-22, 2022-23, 2023-24, 2024-25

The residual is what the operational control did not explain. If it moves with opponent strength, that is signal the control could have used and did not.

### Attacking side — MID, FWD against `opponent_defence_strength`

| Quartile | Rows | Mean opponent strength | Mean realized | Mean residual |
| --- | ---: | ---: | ---: | ---: |
| Q1 | 14,376 | 8.9049 | 1.3600 | +0.0542 |
| Q2 | 13,938 | 14.2708 | 1.3538 | +0.0362 |
| Q3 | 13,896 | 18.4906 | 1.3305 | +0.0057 |
| Q4 | 14,053 | 26.2982 | 1.2288 | -0.1081 |

- Raw spread (Q1 minus Q4): **+0.1311**, monotone
- Residual spread (Q1 minus Q4): **+0.1622**, monotone
- Surviving ratio (residual / raw): **1.24x**

### Defensive side — GK, DEF against `opponent_attack_strength`

| Quartile | Rows | Mean opponent strength | Mean realized | Mean residual |
| --- | ---: | ---: | ---: | ---: |
| Q1 | 11,583 | 18.4838 | 1.1602 | +0.1121 |
| Q2 | 11,024 | 23.0881 | 1.2067 | +0.1248 |
| Q3 | 11,579 | 27.2459 | 1.0421 | -0.0666 |
| Q4 | 10,998 | 35.2627 | 0.8579 | -0.2097 |

- Raw spread (Q1 minus Q4): **+0.3024**, not monotone
- Residual spread (Q1 minus Q4): **+0.3218**, not monotone
- Surviving ratio (residual / raw): **1.06x**

## Limits

This is not gate evidence and it is not a candidate. A prediction model that consumes opponent strength changes the expected-points rate and needs its own declaration, frozen fingerprints and a single run under the existing pre-registered conditions.

Quartiles are a coarse instrument: they show whether a relationship exists and roughly how large, not the functional form a model would fit.

The strength estimate is a proxy built from fantasy points split by unit, not a goal model, and it inherits every limitation `features.strength` names.
