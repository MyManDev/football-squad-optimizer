# A carried free transfer valued by a Bellman model: record

Protocol: [component_banked_value_model_prereg.md](component_banked_value_model_prereg.md).
Record: [component_banked_value_model.json](component_banked_value_model.json), written by
`scripts/measure_component_banked_value_model.py --read`. Probes and chains ran at commit
`ac29d0932`; the fixed levels are the [fixed-level record](component_banked_transfer_value.md)'s
chains of the primary cell and its [path diagnostic](component_banked_transfer_value_path_diagnostic.md)'s
1.12 chains. The probe's policy chain reproduces the record's 0 chain season by season.

## Reading: `not_separable` against 1.12, the owner chooses

| Model against | Mean a week | 90% interval | 2021-22 | 2022-23 | 2023-24 | 2024-25 | Side |
|---|---|---|---|---|---|---|---|
| 1.12 (primary) | +1.16 | [-0.35, +3.19] | +136 | +25 | +19 | -9 | not separable |
| 0 (policy before v3) | +1.29 | [-0.29, +3.43] | -28 | +90 | +21 | +106 | fails the gate |
| 0.5 | -1.31 | [-2.98, +0.75] | -28 | -62 | -68 | -35 | not separable |

The model is ahead of 1.12 in three seasons of four and by +1.16 a week, but the interval
holds zero, so by the protocol the owner chooses. It is behind 0.5 in every season, though
not separably.

## The value function

Mean opportunity over the 147 states: the 1st to 5th free transfer adds 2.11, 2.05, 1.53,
1.19 and 0.88 points to the week's plan; the first is worth nothing in 3% of weeks.

Marginal value of the `k`-th transfer carried (`w_2..w_5`), each season from the other three:

| Season | Through the season | At the last-but-one decision |
|---|---|---|
| 2021-22 | 2.70, 2.27, 1.94, 1.53 | 1.98, 1.38, 1.07, 0.77 |
| 2022-23 | 2.83, 2.45, 2.10, 1.66 | 2.02, 1.54, 1.17, 0.87 |
| 2023-24 | 3.07, 2.62, 2.19, 1.70 | see the record |
| 2024-25 | 3.00, 2.60, 2.19, 1.71 | see the record |

The values fall with each transfer carried, are zero past the cap and at the season's last
decision, and are flat through most of a season: with independent weeks the long horizon
settles to a stationary value until the last few decisions.

The same model on all four seasons' 147 decisions (`all_seasons_value_table` in the
record) is what a product policy carries, by the decisions left after this one:

| Decisions left | 2nd | 3rd | 4th | 5th |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |
| 1 | 2.05 | 1.53 | 1.19 | 0.88 |
| 2 | 2.34 | 1.91 | 1.61 | 1.37 |
| 3 | 2.53 | 2.13 | 1.86 | 1.50 |
| 6 | 2.82 | 2.41 | 2.06 | 1.63 |
| 13 or more | 2.90 | 2.48 | 2.11 | 1.65 |

The first carried transfer is earned in every week the bank is not rebuilt, so it never
changes a decision and carries no value in that table.

## What the model does

It holds 2.5 to 3.7 free transfers on average, pays no hit and loses none at the cap. In
2023-24 and 2024-25 it sits at five for about half the season and spends one a week, keeping
a full reserve. It holds a week's transfer 9 to 18 times a season.

## Limits, as declared

Weeks are independent in the model, so a move skipped this week is treated as gone; in the
game it usually is still there next week. The opportunities are measured from the squad
before each decision, which counts this week's best move among next week's. Both push the
values up, and the first carried transfer at about 2.7 to 3.1 is well above the constants the
fixed-level record found best (0.5) or neutral (1 to 1.2).
