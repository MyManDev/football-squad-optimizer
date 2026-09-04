# Season-long decision chains: lookahead by chips

One squad per season, carried from the first decision gameweek to the last; free
transfers banked, hits paid, prices moving under the game's sell rule, chips spent at
most once inside their window. Every variant shares the projection rule, the pool
rule, the opening squad, and the scoring. Measurement only; nothing is promoted.

## Season totals (net of hits)

| Season | Variant | Decisions | Realized | Hits | Net | Transfers | Chips played | Chip gains | Proven |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| 2021-22 | L1_chips_off | 37 | 2217 | 212 | 2005 | 90 | — | — | 1.00 |
| 2021-22 | L1_chips_reserve | 37 | 2321 | 192 | 2129 | 101 | GW3 wildcard, GW21 wildcard, GW22 bboost, GW23 3xc | 3xc +2, bboost +26, wildcard +56 | 1.00 |
| 2021-22 | L1_chips_value | 37 | 2259 | 184 | 2075 | 101 | GW2 bboost, GW5 wildcard, GW21 wildcard, GW36 3xc | 3xc +20, bboost +21, wildcard +64 | 1.00 |
| 2022-23 | L1_chips_off | 36 | 2201 | 188 | 2013 | 83 | — | — | 1.00 |
| 2022-23 | L1_chips_reserve | 36 | 2211 | 164 | 2047 | 99 | GW3 wildcard, GW17 wildcard, GW19 bboost, GW20 3xc | 3xc +7, bboost +14, wildcard +80 | 1.00 |
| 2022-23 | L1_chips_value | 36 | 2211 | 164 | 2047 | 99 | GW2 bboost, GW3 wildcard, GW17 wildcard, GW22 3xc | 3xc +20, bboost +2, wildcard +80 | 1.00 |
| 2023-24 | L1_chips_off | 37 | 1887 | 144 | 1743 | 73 | — | — | 1.00 |
| 2023-24 | L1_chips_reserve | 37 | 1892 | 128 | 1764 | 83 | GW3 wildcard, GW7 bboost, GW21 wildcard, GW25 3xc | 3xc +4, bboost +17, wildcard +48 | 1.00 |
| 2023-24 | L1_chips_value | 37 | 2012 | 84 | 1928 | 77 | GW2 bboost, GW9 wildcard, GW23 wildcard, GW35 3xc | 3xc +8, bboost +10, wildcard +68 | 1.00 |
| 2024-25 | L1_chips_off | 37 | 2046 | 124 | 1922 | 68 | — | — | 1.00 |
| 2024-25 | L1_chips_reserve | 37 | 2185 | 92 | 2093 | 80 | GW3 wildcard, GW20 wildcard, GW24 3xc, GW25 bboost | 3xc +29, bboost +10, wildcard +68 | 1.00 |
| 2024-25 | L1_chips_value | 37 | 2100 | 80 | 2020 | 82 | GW2 bboost, GW7 wildcard, GW25 3xc, GW29 wildcard | 3xc +20, bboost +13, wildcard +92 | 1.00 |

## Paired comparisons

Season advantage is the difference of season nets; the weekly interval is a
season-aware moving-block bootstrap (90%) on per-gameweek paired differences,
blocks of consecutive weeks because a carried squad makes weeks dependent.

| Variant | vs | Seasons | Mean season delta | Season delta by season | Hits delta by season | Weekly mean ± SE | 90% interval | Weeks > 0 |
| --- | --- | ---: | ---: | --- | --- | ---: | --- | ---: |
| L1_chips_reserve | L1_chips_off | 4 | +87.50 | 2021-22 +124, 2022-23 +34, 2023-24 +21, 2024-25 +171 | 2021-22 -20, 2022-23 -24, 2023-24 -16, 2024-25 -32 | +2.38 ± 0.69 | [+1.31, +3.75] | 0.52 |
| L1_chips_value | L1_chips_off | 4 | +96.75 | 2021-22 +70, 2022-23 +34, 2023-24 +185, 2024-25 +98 | 2021-22 -28, 2022-23 -24, 2023-24 -60, 2024-25 -44 | +2.63 ± 0.76 | [+1.24, +3.86] | 0.51 |

## Assumptions recorded with this run

- Projection rule: `naive_calendar_scaling_v1` (decision-time baseline scaled by fixture count); the measurement is of the planning mechanism, not of projection quality.
- Chip windows per development season are assumed, not read from a capture: 2021-22: first wildcard through GW20; 2022-23: first wildcard through GW16; 2023-24: first wildcard through GW20; 2024-25: first wildcard through GW19; one bench boost and one triple captain per season; free hit not modelled.
- Free-transfer bank cap per season: 2021-22 2, 2022-23 2, 2023-24 2, 2024-25 5.
- Sell price: purchase price plus half of any rise, rounded down to a tenth; buy price is the week's market price. No automatic substitutions; a blank-team squad member scores zero.
- The first decision gameweek is the season's second (in-season features need one prior gameweek); the opening squad is optimized from that week's pool.
- Seasons: 2021-22, 2022-23, 2023-24, 2024-25. The 2025-26 holdout was not read.
