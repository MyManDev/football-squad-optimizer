# What actually happened, per settled gameweek

Contract: `settled_outcome_v1` / `settled_outcome_export_v1`

One row per player per settled gameweek: what the settled capture says he did,
beside what the capture the week was decided from said about whether he could play.
The tables themselves are evidence and are not committed; these are the numbers a
reader needs to check the record without them.

| gw | rows | appeared | started | pre-deadline lead | no availability |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 659 | 307 | 220 | 2.5 h | 3 |
| 5 | 667 | 302 | 220 | 5.08 h | 8 |

A player the pre-deadline capture never listed has **no** availability rather than
a zero one: he was not in the squad that week, and filling in a multiplier would
turn an absence into a statement.

## Inside the block the rule does not separate

| gw | multiplier exactly 1.0 | did not start | did not appear |
| ---: | ---: | ---: | ---: |
| 4 | 474 | 255 | 171 |
| 5 | 464 | 249 | 169 |

Counts, and nothing more. The availability rule is applied once from the capture and
makes no distinction among the players it prices at one; how many of them then did
not start is a fact about those weeks, not evidence that anything should have known
better. What could be predicted, by what, and whether acting on it earns points are
three separate questions and none of them is asked here.

## What this decides

Nothing. No gate is evaluated, no model is promoted, no operational control moves
and no probability is published. The locked holdout is not read: every row comes
from a capture we took ourselves, this season, after the gameweek it describes.

Gameweeks accumulated: 2. Skipped: 3.

Skipped, with reasons:

- gw01: no capture was taken before its deadline 2026-08-21T17:30:00Z, so the availability that applied was never recorded
- gw02: no capture was taken before its deadline 2026-08-28T17:30:00Z, so the availability that applied was never recorded
- gw03: no capture was taken before its deadline 2026-09-04T17:30:00Z, so the availability that applied was never recorded
