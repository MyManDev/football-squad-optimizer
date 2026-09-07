# Member planning policy: transfer hit cost grid (local, not committed)

Lookahead-1 season chain, chips off (the member path's planner offers no chip unless the
operator names one), five seasons with 2025-26 walked as declared development data
(`--development-scope v2`), deterministic budget 8 per solve. The game charges 4 per
extra transfer on every sheet; the planner's hit cost above 4 is a caution margin on
projected gains, not a rule change.

## Season nets by planning hit cost (net of the game's 4-point hits)

| Season | hit 4 | hit 5 | hit 6 | hit 7 | hit 8 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021-22 | 1994 (hits 216) | 1957 (hits 180) | 1942 (hits 116) | 1983 (hits 76) | 2020 (hits 64) |
| 2022-23 | 2013 (hits 188) | 2076 (hits 124) | 2056 (hits 84) | 2076 (hits 60) | 2077 (hits 44) |
| 2023-24 | 1724 (hits 144) | 1771 (hits 96) | 1780 (hits 72) | 1855 (hits 32) | 1846 (hits 24) |
| 2024-25 | 1919 (hits 124) | 2001 (hits 84) | 1972 (hits 60) | 2021 (hits 16) | 2011 (hits 12) |
| 2025-26 | 1657 (hits 100) | 1731 (hits 52) | 1756 (hits 28) | 1761 (hits 12) | 1802 (hits 4) |

## Pooled net points per week and the paired comparison with hit cost 4

| Hit cost | Net/week | Mean season net | Mean season hits | Season spread | vs 4: weekly mean | 90% interval | Season delta by season | Worse seasons | Rule |
| ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | --- |
| 4 | 50.58 | 1861.4 | 154.4 | 356 | — | — | — | — | baseline |
| 5 | 51.83 | 1907.2 | 107.2 | 345 | +1.24 | [+0.34, +2.18] | 2021-22 -37, 2022-23 +63, 2023-24 +47, 2024-25 +82, 2025-26 +74 | 1 | passes |
| 6 | 51.66 | 1901.2 | 72.0 | 300 | +1.08 | [-0.13, +2.02] | 2021-22 -52, 2022-23 +43, 2023-24 +56, 2024-25 +53, 2025-26 +99 | 1 | fails |
| 7 | 52.70 | 1939.2 | 39.2 | 315 | +2.11 | [+0.83, +3.44] | 2021-22 -11, 2022-23 +63, 2023-24 +131, 2024-25 +102, 2025-26 +104 | 1 | passes |
| 8 | 53.02 | 1951.2 | 29.6 | 275 | +2.44 | [+1.04, +3.94] | 2021-22 +26, 2022-23 +64, 2023-24 +122, 2024-25 +92, 2025-26 +145 | 0 | passes |

## Decision

Rule (declared before the run): change the default only if a level beats 4 in pooled mean weekly net AND its 90% interval excludes zero AND it is not worse than 4 in more than one season.

Levels passing: [5, 7, 8]; the best of them by pooled weekly mean is **8**.

The rule fires, and this pull request still ships `member_planning_policy_v1` at hit
cost 4. Acting on the reading is a second change, not this one: it moves what every
league member is told, so it must re-pin `IN_SEASON_MEMBER_ADVICE_SHA256` in
`tests/unit/test_league_views.py` and the site fixture under `web/public/data` in the
same commit -- files this pull request does not own and another line of work is editing.
That is exactly the revisit rule the policy's own docstring states, and it is owed a
pull request of its own with an owner's decision behind it. Nothing here is promoted.

## What this does and does not say

- **It disagrees with `transfer_discipline` (2026-08-17), and not only because of the
  fifth season.** That measurement walked the chain with chips under the reservation
  rule and found hit cost 6 and 8 *worse* than 4 (-29 and -27 mean season net); this one
  walks it with **chips off**, which is what the member path actually does -- it offers no
  chip unless the operator names one. Chip mode is a real difference in configuration, so
  the two readings are not the same experiment run twice, and the older verdict is not
  overturned on its own terms. 2021-22, the season that carried that artifact's negative
  (-236 at hit 6), is only -52 here and turns +26 at hit 8.
- **2025-26 is declared development data**, the Phase C v2 scope: a season this repository
  has used before. Its cells are development evidence and are not an unseen final test.
- **The gain is mostly hits not paid.** Paid transfers fall from 193 across the five
  seasons at cost 4 to 37 at cost 8, and season hit points from 154 to 30 on average. The
  reading is consistent with the discipline note's own diagnosis -- the projection's early
  weeks are optimistic, so a paid transfer bought on them tends to lose -- and a caution
  margin is a way of not paying for that optimism, not a claim that the game charges more.
- **One projection rule, one solver budget, five seasons.** Deterministic budget 8 per
  solve; proven share 0.972 to 1.000, so the solves are
  essentially all proven and the differences are not solver noise. The interval is a
  season-aware moving-block bootstrap on 184 paired gameweeks; a season is still one
  observation, and five is not many.

## Timing

25 cells, 4 workers, 1116 s wall in total; per cell 2025-26/hit4 195s, 2025-26/hit5 226s, 2025-26/hit6 212s, 2025-26/hit7 169s, 2025-26/hit8 199s, 2021-22/hit4 206s, 2021-22/hit5 270s, 2021-22/hit6 234s, 2021-22/hit7 239s, 2021-22/hit8 192s, 2022-23/hit4 153s, 2022-23/hit5 183s, 2022-23/hit6 141s, 2022-23/hit7 130s, 2022-23/hit8 121s, 2023-24/hit4 123s, 2023-24/hit5 124s, 2023-24/hit6 131s, 2023-24/hit7 116s, 2023-24/hit8 129s, 2024-25/hit4 154s, 2024-25/hit5 143s, 2024-25/hit6 143s, 2024-25/hit7 116s, 2024-25/hit8 116s
