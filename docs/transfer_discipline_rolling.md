# Transfer discipline on the season-long chain

Planning hit cost, per-gameweek transfer cap, and terminal value of a banked free
transfer, as a full factorial on the season chain; the sheet charges the rule's four
points a hit throughout. Every cell against the rule cell (cost 4, no cap, value 0) at
the same lookahead and chip mode. Measurement only; nothing is promoted.

## Main effects (mean season net delta vs the rule cell, over the other factors)

### L3: planning hit cost

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| 4 | 8 | +69.8 | 124 |
| 8 | 8 | +114.8 | 64 |

### L3: transfer cap

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| none | 8 | +44.6 | 188 |
| 1 | 8 | +139.9 | 0 |

### L3: banked transfer value

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| 0 | 16 | +92.2 | 94 |

## Cells (mean over seasons)

| Variant | Seasons | Mean net | Mean realized | Mean hits | Mean transfers | Mean season delta vs rule | Weekly mean ± SE | 90% interval |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| L3_chips_reserve_hit4_capnone_ftv0 | 4 | 1877 | 2126 | 249 | 117 | rule | — | — |
| L3_chips_reserve_hit4_cap1_ftv0 | 4 | 2016 | 2016 | 0 | 53 | +139.5 | +3.80 ± 1.11 | [+2.18, +5.78] |
| L3_chips_reserve_hit8_capnone_ftv0 | 4 | 1966 | 2093 | 127 | 86 | +89.2 | +2.43 ± 0.94 | [+1.13, +4.22] |
| L3_chips_reserve_hit8_cap1_ftv0 | 4 | 2017 | 2017 | 0 | 52 | +140.2 | +3.82 ± 1.10 | [+2.15, +5.52] |

Seasons: 2021-22, 2022-23, 2023-24, 2024-25. Projection rule `naive_calendar_scaling_v1`; the 2025-26 holdout was not read.
