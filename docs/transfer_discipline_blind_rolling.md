# Transfer discipline on the season-long chain

Planning hit cost, per-gameweek transfer cap, and terminal value of a banked free
transfer, as a full factorial on the season chain; the sheet charges the rule's four
points a hit throughout. Every cell against the rule cell (cost 4, no cap, value 0) at
the same lookahead and chip mode. Measurement only; nothing is promoted.

## Main effects (mean season net delta vs the rule cell, over the other factors)

### L3: planning hit cost

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| 4 | 8 | +61.2 | 100 |

### L3: transfer cap

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| none | 4 | +0.0 | 201 |
| 1 | 4 | +122.5 | 0 |

### L3: banked transfer value

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| 0 | 8 | +61.2 | 100 |

## Cells (mean over seasons)

| Variant | Seasons | Mean net | Mean realized | Mean hits | Mean transfers | Mean season delta vs rule | Weekly mean ± SE | 90% interval |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| L3_chips_reserve_hit4_capnone_ftv0 | 4 | 1836 | 2037 | 201 | 104 | rule | — | — |
| L3_chips_reserve_hit4_cap1_ftv0 | 4 | 1959 | 1959 | 0 | 52 | +122.5 | +3.33 ± 1.04 | [+1.89, +5.18] |

Seasons: 2021-22, 2022-23, 2023-24, 2024-25. Projection rule `naive_calendar_scaling_v1`; the 2025-26 holdout was not read.
