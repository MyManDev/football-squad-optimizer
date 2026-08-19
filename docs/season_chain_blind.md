# Season-long decision chains: lookahead by chips

One squad per season, carried from the first decision gameweek to the last; free
transfers banked, hits paid, prices moving under the game's sell rule, chips spent at
most once inside their window. Every variant shares the projection rule, the pool
rule, the opening squad, and the scoring. Measurement only; nothing is promoted.

## Season totals (net of hits)

| Season | Variant | Decisions | Realized | Hits | Net | Transfers | Chips played | Chip gains | Proven |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| 2021-22 | L1_chips_off | 37 | 1990 | 92 | 1898 | 60 | — | — | 1.00 |
| 2021-22 | L1_chips_reserve | 37 | 2097 | 92 | 2005 | 74 | GW3 wildcard, GW21 wildcard, GW22 bboost, GW23 3xc | 3xc +2, bboost +10, wildcard +48 | 1.00 |
| 2021-22 | L1_chips_value | 37 | 1981 | 84 | 1897 | 77 | GW2 bboost, GW5 wildcard, GW24 wildcard | bboost +21, wildcard +68 | 1.00 |
| 2022-23 | L1_chips_off | 36 | 1953 | 100 | 1853 | 61 | — | — | 0.97 |
| 2022-23 | L1_chips_reserve | 36 | 1990 | 88 | 1902 | 80 | GW3 wildcard, GW17 wildcard, GW19 bboost, GW20 3xc | 3xc +9, bboost +10, wildcard +80 | 0.97 |
| 2022-23 | L1_chips_value | 36 | 1974 | 88 | 1886 | 80 | GW2 bboost, GW3 wildcard, GW17 wildcard | bboost +2, wildcard +80 | 0.97 |
| 2023-24 | L1_chips_off | 37 | 1908 | 80 | 1828 | 57 | — | — | 1.00 |
| 2023-24 | L1_chips_reserve | 37 | 1837 | 88 | 1749 | 75 | GW3 wildcard, GW7 bboost, GW21 wildcard, GW25 3xc | 3xc +2, bboost +17, wildcard +56 | 1.00 |
| 2023-24 | L1_chips_value | 37 | 2013 | 52 | 1961 | 68 | GW2 bboost, GW9 wildcard, GW23 wildcard | bboost +10, wildcard +64 | 1.00 |
| 2024-25 | L1_chips_off | 37 | 1957 | 84 | 1873 | 58 | — | — | 1.00 |
| 2024-25 | L1_chips_reserve | 37 | 2054 | 64 | 1990 | 73 | GW3 wildcard, GW20 wildcard, GW24 3xc, GW25 bboost | 3xc +2, bboost +7, wildcard +68 | 1.00 |
| 2024-25 | L1_chips_value | 37 | 1968 | 52 | 1916 | 76 | GW2 bboost, GW7 wildcard, GW29 wildcard | bboost +13, wildcard +96 | 1.00 |

## Paired comparisons

Season advantage is the difference of season nets; the weekly interval is a
season-aware moving-block bootstrap (90%) on per-gameweek paired differences,
blocks of consecutive weeks because a carried squad makes weeks dependent.

| Variant | vs | Seasons | Mean season delta | Season delta by season | Hits delta by season | Weekly mean ± SE | 90% interval | Weeks > 0 |
| --- | --- | ---: | ---: | --- | --- | ---: | --- | ---: |
| L1_chips_reserve | L1_chips_off | 4 | +48.50 | 2021-22 +107, 2022-23 +49, 2023-24 -79, 2024-25 +117 | 2021-22 +0, 2022-23 -12, 2023-24 +8, 2024-25 -20 | +1.32 ± 0.84 | [-0.08, +2.78] | 0.52 |
| L1_chips_value | L1_chips_off | 4 | +52.00 | 2021-22 -1, 2022-23 +33, 2023-24 +133, 2024-25 +43 | 2021-22 -8, 2022-23 -12, 2023-24 -28, 2024-25 -32 | +1.41 ± 0.78 | [+0.09, +2.53] | 0.46 |

## Assumptions recorded with this run

- Projection rule: `control_calendar_blind_v1` (the decision-time operational control projection, scaled by the known fixture count under naive_calendar_scaling_v1, unscaled under control_calendar_blind_v1); the measurement is of the planning mechanism.
- Chip windows per development season are assumed, not read from a capture: 2021-22: first wildcard through GW20; 2022-23: first wildcard through GW16; 2023-24: first wildcard through GW20; 2024-25: first wildcard through GW19; one bench boost, one triple captain, and one free hit per season.
- Free-transfer bank cap per season: 2021-22 2, 2022-23 2, 2023-24 2, 2024-25 5.
- Sell price: purchase price plus half of any rise, rounded down to a tenth; buy price is the week's market price. No automatic substitutions; a blank-team squad member scores zero.
- The first decision gameweek is the season's second (in-season features need one prior gameweek); the opening squad is optimized from that week's pool.
- Seasons: 2021-22, 2022-23, 2023-24, 2024-25. The 2025-26 holdout was not read.
