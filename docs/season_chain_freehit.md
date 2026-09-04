# Season-long decision chains: lookahead by chips

One squad per season, carried from the first decision gameweek to the last; free
transfers banked, hits paid, prices moving under the game's sell rule, chips spent at
most once inside their window. Every variant shares the projection rule, the pool
rule, the opening squad, and the scoring. Measurement only; nothing is promoted.

## Season totals (net of hits)

| Season | Variant | Decisions | Realized | Hits | Net | Transfers | Chips played | Chip gains | Proven |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| 2021-22 | L1_chips_off | 37 | 2217 | 212 | 2005 | 90 | — | — | 1.00 |
| 2021-22 | L1_chips_reserve | 37 | 2315 | 188 | 2127 | 110 | GW3 wildcard, GW21 wildcard, GW22 bboost, GW23 3xc, GW25 freehit | 3xc +2, bboost +26, freehit +12, wildcard +56 | 1.00 |
| 2021-22 | L1_chips_hybrid | 37 | 2257 | 172 | 2085 | 109 | GW2 3xc, GW5 wildcard, GW21 wildcard, GW25 freehit, GW28 bboost | 3xc +1, bboost +12, freehit +16, wildcard +64 | 1.00 |
| 2022-23 | L1_chips_off | 36 | 2201 | 188 | 2013 | 83 | — | — | 1.00 |
| 2022-23 | L1_chips_reserve | 36 | 2225 | 156 | 2069 | 105 | GW3 wildcard, GW17 wildcard, GW19 bboost, GW20 3xc, GW22 freehit | 3xc +7, bboost +14, freehit -15, wildcard +80 | 1.00 |
| 2022-23 | L1_chips_hybrid | 36 | 2225 | 136 | 2089 | 105 | GW3 wildcard, GW17 wildcard, GW22 3xc, GW25 freehit, GW29 bboost | 3xc +20, bboost +34, freehit +20, wildcard +80 | 1.00 |
| 2023-24 | L1_chips_off | 37 | 1887 | 144 | 1743 | 73 | — | — | 1.00 |
| 2023-24 | L1_chips_reserve | 37 | 1905 | 104 | 1801 | 88 | GW3 wildcard, GW7 bboost, GW21 wildcard, GW25 freehit, GW28 3xc | 3xc +4, bboost +7, freehit +21, wildcard +48 | 1.00 |
| 2023-24 | L1_chips_hybrid | 37 | 2017 | 84 | 1933 | 86 | GW9 wildcard, GW23 wildcard, GW25 freehit, GW35 3xc, GW37 bboost | 3xc +8, bboost +51, freehit +24, wildcard +68 | 1.00 |
| 2024-25 | L1_chips_off | 37 | 2046 | 124 | 1922 | 68 | — | — | 1.00 |
| 2024-25 | L1_chips_reserve | 37 | 2177 | 80 | 2097 | 86 | GW3 wildcard, GW20 wildcard, GW24 3xc, GW25 bboost, GW32 freehit | 3xc +29, bboost +10, freehit +16, wildcard +68 | 1.00 |
| 2024-25 | L1_chips_hybrid | 37 | 2105 | 72 | 2033 | 91 | GW7 wildcard, GW25 3xc, GW29 wildcard, GW32 freehit | 3xc +20, freehit +9, wildcard +92 | 1.00 |

## Paired comparisons

Season advantage is the difference of season nets; the weekly interval is a
season-aware moving-block bootstrap (90%) on per-gameweek paired differences,
blocks of consecutive weeks because a carried squad makes weeks dependent.

| Variant | vs | Seasons | Mean season delta | Season delta by season | Hits delta by season | Weekly mean ± SE | 90% interval | Weeks > 0 |
| --- | --- | ---: | ---: | --- | --- | ---: | --- | ---: |
| L1_chips_reserve | L1_chips_off | 4 | +102.75 | 2021-22 +122, 2022-23 +56, 2023-24 +58, 2024-25 +175 | 2021-22 -24, 2022-23 -32, 2023-24 -40, 2024-25 -44 | +2.80 ± 0.76 | [+1.56, +4.27] | 0.55 |
| L1_chips_hybrid | L1_chips_off | 4 | +114.25 | 2021-22 +80, 2022-23 +76, 2023-24 +190, 2024-25 +111 | 2021-22 -40, 2022-23 -52, 2023-24 -60, 2024-25 -52 | +3.11 ± 0.79 | [+1.82, +4.69] | 0.52 |

## Assumptions recorded with this run

- Projection rule: `naive_calendar_scaling_v1` (the decision-time operational control projection, scaled by the known fixture count under naive_calendar_scaling_v1, unscaled under control_calendar_blind_v1); the measurement is of the planning mechanism.
- Chip windows per development season are assumed, not read from a capture: 2021-22: first wildcard through GW20; 2022-23: first wildcard through GW16; 2023-24: first wildcard through GW20; 2024-25: first wildcard through GW19; one bench boost, one triple captain, and one free hit per season.
- Free-transfer bank cap per season: 2021-22 2, 2022-23 2, 2023-24 2, 2024-25 5.
- Sell price: purchase price plus half of any rise, rounded down to a tenth; buy price is the week's market price. No automatic substitutions; a blank-team squad member scores zero.
- The first decision gameweek is the season's second (in-season features need one prior gameweek); the opening squad is optimized from that week's pool.
- Seasons: 2021-22, 2022-23, 2023-24, 2024-25. The 2025-26 holdout was not read.
