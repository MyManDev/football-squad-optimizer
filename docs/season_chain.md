# Season-long decision chains: lookahead by chips

One squad per season, carried from the first decision gameweek to the last; free
transfers banked, hits paid, prices moving under the game's sell rule, chips spent at
most once inside their window. Every variant shares the projection rule, the pool
rule, the opening squad, and the scoring. Measurement only; nothing is promoted.

## Season totals (net of hits)

| Season | Variant | Decisions | Realized | Hits | Net | Transfers | Chips played | Chip gains | Proven |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| 2021-22 | L1_chips_off | 37 | 2217 | 212 | 2005 | 90 | — | — | 1.00 |
| 2021-22 | L1_chips_on | 37 | 2250 | 196 | 2054 | 103 | GW2 bboost, GW3 3xc, GW4 wildcard, GW21 wildcard | 3xc +11, bboost +21, wildcard +60 | 0.97 |
| 2021-22 | L1_chips_reserve | 37 | 2321 | 192 | 2129 | 101 | GW3 wildcard, GW21 wildcard, GW22 bboost, GW23 3xc | 3xc +2, bboost +26, wildcard +56 | 1.00 |
| 2021-22 | L3_chips_off | 37 | 2125 | 416 | 1709 | 141 | — | — | 0.32 |
| 2021-22 | L3_chips_on | 37 | 2104 | 352 | 1752 | 141 | GW3 wildcard, GW4 3xc, GW16 bboost, GW21 wildcard | 3xc -1, bboost +22, wildcard +56 | 0.46 |
| 2021-22 | L3_chips_reserve | 37 | 2170 | 340 | 1830 | 137 | GW3 wildcard, GW21 wildcard, GW22 bboost, GW26 3xc | 3xc +13, bboost +17, wildcard +52 | 0.35 |
| 2022-23 | L1_chips_off | 36 | 2201 | 188 | 2013 | 83 | — | — | 1.00 |
| 2022-23 | L1_chips_on | 36 | 2193 | 164 | 2029 | 99 | GW2 bboost, GW3 wildcard, GW4 3xc, GW17 wildcard | 3xc +2, bboost +2, wildcard +80 | 1.00 |
| 2022-23 | L1_chips_reserve | 36 | 2211 | 164 | 2047 | 99 | GW3 wildcard, GW17 wildcard, GW19 bboost, GW20 3xc | 3xc +7, bboost +14, wildcard +80 | 1.00 |
| 2022-23 | L3_chips_off | 36 | 2146 | 308 | 1838 | 113 | — | — | 0.53 |
| 2022-23 | L3_chips_on | 36 | 2145 | 248 | 1897 | 119 | GW3 wildcard, GW4 3xc, GW6 bboost, GW17 wildcard | 3xc +2, bboost +3, wildcard +76 | 0.64 |
| 2022-23 | L3_chips_reserve | 36 | 2222 | 224 | 1998 | 113 | GW3 wildcard, GW17 wildcard, GW19 bboost, GW20 3xc | 3xc +7, bboost +26, wildcard +76 | 0.69 |
| 2023-24 | L1_chips_off | 37 | 1887 | 144 | 1743 | 73 | — | — | 1.00 |
| 2023-24 | L1_chips_on | 37 | 1913 | 120 | 1793 | 84 | GW2 bboost, GW3 3xc, GW4 wildcard, GW21 wildcard | 3xc +2, bboost +10, wildcard +60 | 1.00 |
| 2023-24 | L1_chips_reserve | 37 | 1892 | 128 | 1764 | 83 | GW3 wildcard, GW7 bboost, GW21 wildcard, GW25 3xc | 3xc +4, bboost +17, wildcard +48 | 1.00 |
| 2023-24 | L3_chips_off | 37 | 1989 | 244 | 1745 | 98 | — | — | 0.78 |
| 2023-24 | L3_chips_on | 37 | 1946 | 240 | 1706 | 112 | GW3 wildcard, GW7 3xc, GW21 wildcard, GW25 bboost | 3xc +10, bboost +17, wildcard +52 | 0.73 |
| 2023-24 | L3_chips_reserve | 37 | 1945 | 220 | 1725 | 109 | GW3 wildcard, GW7 bboost, GW21 wildcard, GW25 3xc | 3xc +4, bboost +16, wildcard +60 | 0.76 |
| 2024-25 | L1_chips_off | 37 | 2046 | 124 | 1922 | 68 | — | — | 1.00 |
| 2024-25 | L1_chips_on | 37 | 2172 | 88 | 2084 | 76 | GW2 bboost, GW3 3xc, GW4 wildcard, GW20 wildcard | 3xc +17, bboost +13, wildcard +60 | 1.00 |
| 2024-25 | L1_chips_reserve | 37 | 2185 | 92 | 2093 | 80 | GW3 wildcard, GW20 wildcard, GW24 3xc, GW25 bboost | 3xc +29, bboost +10, wildcard +68 | 1.00 |
| 2024-25 | L3_chips_off | 37 | 2014 | 248 | 1766 | 99 | — | — | 0.57 |
| 2024-25 | L3_chips_on | 37 | 2107 | 220 | 1887 | 108 | GW3 wildcard, GW4 3xc, GW20 wildcard, GW24 bboost | 3xc +2, bboost +11, wildcard +52 | 0.59 |
| 2024-25 | L3_chips_reserve | 37 | 2167 | 212 | 1955 | 108 | GW3 wildcard, GW20 wildcard, GW24 bboost, GW25 3xc | 3xc +20, bboost +11, wildcard +60 | 0.62 |

## Paired comparisons

Season advantage is the difference of season nets; the weekly interval is a
season-aware moving-block bootstrap (90%) on per-gameweek paired differences,
blocks of consecutive weeks because a carried squad makes weeks dependent.

| Variant | vs | Seasons | Mean season delta | Season delta by season | Hits delta by season | Weekly mean ± SE | 90% interval | Weeks > 0 |
| --- | --- | ---: | ---: | --- | --- | ---: | --- | ---: |
| L1_chips_on | L1_chips_off | 4 | +69.25 | 2021-22 +49, 2022-23 +16, 2023-24 +50, 2024-25 +162 | 2021-22 -16, 2022-23 -24, 2023-24 -24, 2024-25 -36 | +1.88 ± 0.76 | [+0.56, +2.99] | 0.50 |
| L1_chips_reserve | L1_chips_off | 4 | +87.50 | 2021-22 +124, 2022-23 +34, 2023-24 +21, 2024-25 +171 | 2021-22 -20, 2022-23 -24, 2023-24 -16, 2024-25 -32 | +2.38 ± 0.69 | [+1.31, +3.75] | 0.52 |
| L3_chips_off | L1_chips_off | 4 | -156.25 | 2021-22 -296, 2022-23 -175, 2023-24 +2, 2024-25 -156 | 2021-22 +204, 2022-23 +120, 2023-24 +100, 2024-25 +124 | -4.25 ± 1.06 | [-6.35, -2.79] | 0.35 |
| L3_chips_on | L1_chips_off | 4 | -110.25 | 2021-22 -253, 2022-23 -116, 2023-24 -37, 2024-25 -35 | 2021-22 +140, 2022-23 +60, 2023-24 +96, 2024-25 +96 | -3.00 ± 1.03 | [-5.08, -1.56] | 0.39 |
| L3_chips_reserve | L1_chips_off | 4 | -43.75 | 2021-22 -175, 2022-23 -15, 2023-24 -18, 2024-25 +33 | 2021-22 +128, 2022-23 +36, 2023-24 +76, 2024-25 +88 | -1.19 ± 0.95 | [-2.93, +0.16] | 0.43 |
| L3_chips_on | L3_chips_off | 4 | +46.00 | 2021-22 +43, 2022-23 +59, 2023-24 -39, 2024-25 +121 | 2021-22 -64, 2022-23 -60, 2023-24 -4, 2024-25 -28 | +1.25 ± 0.89 | [-0.50, +2.95] | 0.46 |
| L3_chips_reserve | L3_chips_off | 4 | +112.50 | 2021-22 +121, 2022-23 +160, 2023-24 -20, 2024-25 +189 | 2021-22 -76, 2022-23 -84, 2023-24 -24, 2024-25 -36 | +3.06 ± 0.81 | [+1.66, +4.73] | 0.55 |

## Assumptions recorded with this run

- Projection rule: `naive_calendar_scaling_v1` (decision-time baseline scaled by fixture count); the measurement is of the planning mechanism, not of projection quality.
- Chip windows per development season are assumed, not read from a capture: 2021-22: first wildcard through GW20; 2022-23: first wildcard through GW16; 2023-24: first wildcard through GW20; 2024-25: first wildcard through GW19; one bench boost and one triple captain per season; free hit not modelled.
- Free-transfer bank cap per season: 2021-22 2, 2022-23 2, 2023-24 2, 2024-25 5.
- Sell price: purchase price plus half of any rise, rounded down to a tenth; buy price is the week's market price. No automatic substitutions; a blank-team squad member scores zero.
- The first decision gameweek is the season's second (in-season features need one prior gameweek); the opening squad is optimized from that week's pool.
- Seasons: 2021-22, 2022-23, 2023-24, 2024-25. The 2025-26 holdout was not read.
