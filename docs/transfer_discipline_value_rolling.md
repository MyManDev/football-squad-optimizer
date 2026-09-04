# Transfer discipline on the season-long chain

Planning hit cost, per-gameweek transfer cap, and terminal value of a banked free
transfer, as a full factorial on the season chain; the sheet charges the rule's four
points a hit throughout. Every cell against the rule cell (cost 4, no cap, value 0) at
the same lookahead and chip mode. Measurement only; nothing is promoted.

## Main effects (mean season net delta vs the rule cell, over the other factors)

### L3: planning hit cost

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| 4 | 8 | +64.9 | 130 |

### L3: transfer cap

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| none | 4 | +0.0 | 261 |
| 1 | 4 | +129.8 | 0 |

### L3: banked transfer value

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| 0 | 8 | +64.9 | 130 |

## Cells (mean over seasons)

| Variant | Seasons | Mean net | Mean realized | Mean hits | Mean transfers | Mean season delta vs rule | Weekly mean ± SE | 90% interval |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| L3_chips_value_hit4_capnone_ftv0 | 4 | 1838 | 2099 | 261 | 120 | rule | — | — |
| L3_chips_value_hit4_cap1_ftv0 | 4 | 1968 | 1968 | 0 | 53 | +129.8 | +3.53 ± 0.93 | [+2.15, +5.22] |

Seasons: 2021-22, 2022-23, 2023-24, 2024-25. Projection rule `naive_calendar_scaling_v1`; the 2025-26 holdout was not read.
