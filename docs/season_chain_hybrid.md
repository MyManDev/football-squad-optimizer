# Season-long decision chains: lookahead by chips

One squad per season, carried from the first decision gameweek to the last; free
transfers banked, hits paid, prices moving under the game's sell rule, chips spent at
most once inside their window. Every variant shares the projection rule, the pool
rule, the opening squad, and the scoring. Measurement only; nothing is promoted.

## Season totals (net of hits)

| Season | Variant | Decisions | Realized | Hits | Net | Transfers | Chips played | Chip gains | Proven |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| 2021-22 | L1_chips_off | 37 | 2217 | 212 | 2005 | 90 | — | — | 1.00 |
| 2021-22 | L1_chips_hybrid | 37 | 2260 | 196 | 2064 | 104 | GW2 3xc, GW5 wildcard, GW21 wildcard, GW28 bboost | 3xc +1, bboost +12, wildcard +64 | 1.00 |
| 2022-23 | L1_chips_off | 36 | 2201 | 188 | 2013 | 83 | — | — | 1.00 |
| 2022-23 | L1_chips_hybrid | 36 | 2256 | 176 | 2080 | 102 | GW3 wildcard, GW17 wildcard, GW22 3xc, GW29 bboost | 3xc +20, bboost +37, wildcard +80 | 1.00 |
| 2023-24 | L1_chips_off | 37 | 1887 | 144 | 1743 | 73 | — | — | 1.00 |
| 2023-24 | L1_chips_hybrid | 37 | 2022 | 88 | 1934 | 78 | GW9 wildcard, GW23 wildcard, GW35 3xc, GW37 bboost | 3xc +8, bboost +52, wildcard +68 | 1.00 |
| 2024-25 | L1_chips_off | 37 | 2046 | 124 | 1922 | 68 | — | — | 1.00 |
| 2024-25 | L1_chips_hybrid | 37 | 2092 | 80 | 2012 | 82 | GW7 wildcard, GW25 3xc, GW29 wildcard | 3xc +20, wildcard +92 | 1.00 |

## Paired comparisons

Season advantage is the difference of season nets; the weekly interval is a
season-aware moving-block bootstrap (90%) on per-gameweek paired differences,
blocks of consecutive weeks because a carried squad makes weeks dependent.

| Variant | vs | Seasons | Mean season delta | Season delta by season | Hits delta by season | Weekly mean ± SE | 90% interval | Weeks > 0 |
| --- | --- | ---: | ---: | --- | --- | ---: | --- | ---: |
| L1_chips_hybrid | L1_chips_off | 4 | +101.75 | 2021-22 +59, 2022-23 +67, 2023-24 +191, 2024-25 +90 | 2021-22 -16, 2022-23 -12, 2023-24 -56, 2024-25 -44 | +2.77 ± 0.78 | [+1.50, +4.15] | 0.50 |

## Assumptions recorded with this run

- Projection rule: `naive_calendar_scaling_v1` (the decision-time operational control projection, scaled by the known fixture count under naive_calendar_scaling_v1, unscaled under control_calendar_blind_v1); the measurement is of the planning mechanism.
- Chip windows per development season are assumed, not read from a capture: 2021-22: first wildcard through GW20; 2022-23: first wildcard through GW16; 2023-24: first wildcard through GW20; 2024-25: first wildcard through GW19; one bench boost and one triple captain per season; free hit not modelled.
- Free-transfer bank cap per season: 2021-22 2, 2022-23 2, 2023-24 2, 2024-25 5.
- Sell price: purchase price plus half of any rise, rounded down to a tenth; buy price is the week's market price. No automatic substitutions; a blank-team squad member scores zero.
- The first decision gameweek is the season's second (in-season features need one prior gameweek); the opening squad is optimized from that week's pool.
- Seasons: 2021-22, 2022-23, 2023-24, 2024-25. The 2025-26 holdout was not read.
