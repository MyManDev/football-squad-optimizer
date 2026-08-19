# Transfer discipline on the season-long chain

Planning hit cost, per-gameweek transfer cap, and terminal value of a banked free
transfer, as a full factorial on the season chain; the sheet charges the rule's four
points a hit throughout. Every cell against the rule cell (cost 4, no cap, value 0) at
the same lookahead and chip mode. Measurement only; nothing is promoted.

## Main effects (mean season net delta vs the rule cell, over the other factors)

### L1: planning hit cost

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| 4 | 36 | -27.3 | 71 |
| 6 | 36 | -23.1 | 37 |
| 8 | 36 | -12.9 | 17 |

### L1: transfer cap

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| none | 36 | -20.7 | 84 |
| 2 | 36 | -14.6 | 41 |
| 1 | 36 | -28.0 | 0 |

### L1: banked transfer value

| Level | Cells | Mean season net delta | Mean hit points |
| --- | ---: | ---: | ---: |
| 0 | 36 | -25.2 | 41 |
| 1 | 36 | -25.5 | 43 |
| 2 | 36 | -12.6 | 41 |

## Cells (mean over seasons)

| Variant | Seasons | Mean net | Mean realized | Mean hits | Mean transfers | Mean season delta vs rule | Weekly mean ± SE | 90% interval |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| L1_chips_reserve_hit4_capnone_ftv0 | 4 | 2008 | 2152 | 144 | 91 | rule | — | — |
| L1_chips_reserve_hit4_capnone_ftv1 | 4 | 1971 | 2125 | 154 | 93 | -37.0 | -1.01 ± 0.49 | [-1.97, -0.27] |
| L1_chips_reserve_hit4_capnone_ftv2 | 4 | 1966 | 2116 | 150 | 92 | -41.8 | -1.14 ± 0.58 | [-2.10, -0.38] |
| L1_chips_reserve_hit4_cap2_ftv0 | 4 | 1991 | 2056 | 65 | 72 | -17.2 | -0.47 ± 0.70 | [-1.55, +0.56] |
| L1_chips_reserve_hit4_cap2_ftv1 | 4 | 1956 | 2024 | 68 | 72 | -51.8 | -1.41 ± 0.76 | [-2.70, -0.44] |
| L1_chips_reserve_hit4_cap2_ftv2 | 4 | 1994 | 2054 | 60 | 70 | -14.2 | -0.39 ± 0.78 | [-1.56, +0.81] |
| L1_chips_reserve_hit4_cap1_ftv0 | 4 | 1984 | 1984 | 0 | 54 | -24.8 | -0.67 ± 0.91 | [-1.99, +0.48] |
| L1_chips_reserve_hit4_cap1_ftv1 | 4 | 1969 | 1969 | 0 | 53 | -39.0 | -1.06 ± 0.92 | [-2.42, +0.14] |
| L1_chips_reserve_hit4_cap1_ftv2 | 4 | 1988 | 1988 | 0 | 53 | -20.2 | -0.55 ± 0.92 | [-1.82, +0.61] |
| L1_chips_reserve_hit6_capnone_ftv0 | 4 | 1979 | 2049 | 70 | 72 | -29.0 | -0.79 ± 0.78 | [-1.99, +0.25] |
| L1_chips_reserve_hit6_capnone_ftv1 | 4 | 1984 | 2054 | 71 | 72 | -24.8 | -0.67 ± 0.74 | [-1.76, +0.34] |
| L1_chips_reserve_hit6_capnone_ftv2 | 4 | 1985 | 2061 | 76 | 74 | -23.2 | -0.63 ± 0.78 | [-1.96, +0.33] |
| L1_chips_reserve_hit6_cap2_ftv0 | 4 | 1966 | 2004 | 38 | 65 | -42.8 | -1.16 ± 0.89 | [-2.41, +0.03] |
| L1_chips_reserve_hit6_cap2_ftv1 | 4 | 1996 | 2036 | 40 | 65 | -12.2 | -0.33 ± 0.81 | [-1.73, +0.74] |
| L1_chips_reserve_hit6_cap2_ftv2 | 4 | 2016 | 2056 | 39 | 65 | +8.2 | +0.22 ± 0.82 | [-1.20, +1.27] |
| L1_chips_reserve_hit6_cap1_ftv0 | 4 | 1984 | 1984 | 0 | 54 | -24.8 | -0.67 ± 0.91 | [-1.96, +0.51] |
| L1_chips_reserve_hit6_cap1_ftv1 | 4 | 1969 | 1969 | 0 | 53 | -39.0 | -1.06 ± 0.92 | [-2.43, +0.08] |
| L1_chips_reserve_hit6_cap1_ftv2 | 4 | 1988 | 1988 | 0 | 53 | -20.2 | -0.55 ± 0.92 | [-1.88, +0.61] |
| L1_chips_reserve_hit8_capnone_ftv0 | 4 | 1982 | 2014 | 33 | 64 | -26.8 | -0.73 ± 0.92 | [-1.96, +0.69] |
| L1_chips_reserve_hit8_capnone_ftv1 | 4 | 2008 | 2040 | 32 | 63 | +0.2 | +0.01 ± 0.82 | [-0.87, +1.43] |
| L1_chips_reserve_hit8_capnone_ftv2 | 4 | 2004 | 2033 | 29 | 62 | -4.2 | -0.12 ± 0.88 | [-1.31, +1.16] |
| L1_chips_reserve_hit8_cap2_ftv0 | 4 | 1971 | 1990 | 19 | 60 | -37.2 | -1.01 ± 0.95 | [-2.25, +0.15] |
| L1_chips_reserve_hit8_cap2_ftv1 | 4 | 2021 | 2041 | 20 | 60 | +12.8 | +0.35 ± 0.94 | [-1.02, +1.64] |
| L1_chips_reserve_hit8_cap2_ftv2 | 4 | 2031 | 2049 | 18 | 60 | +23.0 | +0.63 ± 0.91 | [-0.48, +1.91] |
| L1_chips_reserve_hit8_cap1_ftv0 | 4 | 1984 | 1984 | 0 | 54 | -24.8 | -0.67 ± 0.91 | [-2.03, +0.49] |
| L1_chips_reserve_hit8_cap1_ftv1 | 4 | 1969 | 1969 | 0 | 53 | -39.0 | -1.06 ± 0.92 | [-2.37, +0.07] |
| L1_chips_reserve_hit8_cap1_ftv2 | 4 | 1988 | 1988 | 0 | 53 | -20.2 | -0.55 ± 0.92 | [-1.84, +0.54] |

Seasons: 2021-22, 2022-23, 2023-24, 2024-25. Projection rule `naive_calendar_scaling_v1`; the 2025-26 holdout was not read.
