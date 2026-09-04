# What a capture's cumulative counters describe

Contract: `capture_season_phase_v1`

An element record's `minutes`, `total_points`, `starts` and the rest are
cumulative, and which season they accumulate is not stated anywhere in the
payload. Before the platform resets they are the previous season's totals;
afterwards they are this season's. Both are plausible integers, so reading the
wrong one produces a wrong feature and no error.

## Stored captures

| snapshot | captured | phase | agrees with 2025-26 |
| --- | --- | --- | ---: |
| `fpl-live-20260813T201143Z-55789a780186` | 2026-08-13T20:11:43Z | `prior_season` | 452/459 (98.5%) |
| `fpl-live-20260820T170525Z-545aaf5df705` | 2026-08-20T17:05:25Z | `prior_season` | 454/461 (98.5%) |
| `fpl-live-20260822T041036Z-3b0de5aea3e3` | 2026-08-22T04:10:36Z | `current_season` | 55/461 (11.9%) |

## The reset, measured

A capture taken after the first kick-off no longer echoes the completed
season. The clearest form is the players whose accumulated minutes fell
the furthest -- a full previous campaign before, a single appearance or
none after:

| player | before | after |
| --- | ---: | ---: |
| `457569` | 3420 min / 124 pts | 0 min / 0 pts |
| `489639` | 3420 min / 130 pts | 0 min / 0 pts |
| `111234` | 3420 min / 135 pts | 0 min / 0 pts |
| `80201` | 3420 min / 122 pts | 0 min / 0 pts |
| `97032` | 3420 min / 175 pts | 0 min / 0 pts |

Of 461 players compared, 404 had their accumulated
minutes fall. A counter that only ever accumulates cannot fall, so this
is the reset rather than a slow divergence.

55 players still match the completed season, and 55 of
those had no prior-season record at all -- nothing to reset, so their
agreement carries no information. That leaves **0** genuine counterexamples: no player
who held a prior-season record kept it.

A pre-reset capture's counters are not merely *similar* to the completed
season's totals, they are the same integers. That is what makes this a
measurement rather than an interpretation.

## The boundary, and the part of it nobody has observed

The opening deadline is 2026-08-21T17:30:00Z and the season's first
kick-off is 2026-08-21T19:00:00Z. The reset happens somewhere in
between, and no capture exists inside that window, so which of the two
instants triggers it is **unmeasured**. The adapter therefore reports three
phases rather than two: a capture in that window is `unobserved_transition`
and is refused, because guessing there would be an assertion about data
nobody has. A capture taken inside the window would close this.

## What this decides

Nothing on its own. It is the reason `in_season_totals` refuses a pre-reset
capture, and the reason a single capture taken after the opening gameweek
completes is enough to give that gameweek's played history: once the counters
have reset, a season-to-date total after one gameweek *is* that gameweek. From
the third gameweek onward a single total no longer isolates one week, so
consecutive captures must be differenced.

The locked holdout was not read. Fields classified as season-relative: 11.
