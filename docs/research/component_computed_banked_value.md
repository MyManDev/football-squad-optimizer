# A held free transfer's value computed each week: record

Protocol: [component_computed_banked_value_prereg.md](component_computed_banked_value_prereg.md).
Record: [component_computed_banked_value.json](component_computed_banked_value.json), written by
`scripts/measure_component_computed_banked_value.py --read`. The four chains ran at commit
`5717435dc` with the chain code later committed unchanged as `c64f9bd7b`; the fixed levels are
the [fixed-level record](component_banked_transfer_value.md)'s own chains of the primary cell.

## Reading: `unsupported`

| Computed value against | Mean a week | 90% interval | 2021-22 | 2022-23 | 2023-24 | 2024-25 | Side |
|---|---|---|---|---|---|---|---|
| 0 (policy, primary) | -0.16 | [-2.01, +1.62] | -176 | +85 | -30 | +97 | fails the gate |
| 0.5 | -2.76 | [-4.49, -1.19] | -176 | -67 | -119 | -44 | worse |
| 1.2 | -0.90 | [-2.35, +0.83] | -92 | +9 | -32 | -18 | not separable |

The computed value does not beat the policy, loses to the constant 0.5 in every season, and
cannot be told apart from 1.2. No proposal follows; the constants stay as the fixed-level record
reads them.

## Described

| Season | Mean value | Median | Max | Share at 0 | Held where 0 spends | Mean transfers held | Hits paid |
|---|---|---|---|---|---|---|---|
| 2021-22 | 2.67 | 1.79 | 8.0 | 5% | 12 | 1.57 | 0 |
| 2022-23 | 2.14 | 1.15 | 8.0 | 6% | 14 | 1.56 | 0 |
| 2023-24 | 2.02 | 1.07 | 8.0 | 5% | 14 | 1.51 | 0 |
| 2024-25 | 1.79 | 1.26 | 8.0 | 5% | 16 | 1.57 | 0 |

The computed value is large: a median of 1.1 to 1.8 points and a ceiling of 8, the policy's
hit cost, which is what one more free transfer saves when the next move would otherwise be
paid for. The arm holds a transfer the policy spends 12 to 16 times a season, more often than
1.2 does (7 to 13) and far more often than 0.5 (1 to 4).

## Why, as far as this record can say

The rule prices next week's extra free transfer from the squad held **before** this week's
decision, as the protocol declared. That squad still has this week's best move undone, so next
week's second transfer is worth about as much as the move it is meant to price, and the planner
holds transfers it should spend. A value read from the squad **after** the decision would need
the two weeks solved together (a two-week horizon on a forecast that covers one week); it is not
measured here.
