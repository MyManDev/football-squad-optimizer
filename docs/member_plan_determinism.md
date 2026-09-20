# The one-week member plan, at 6 wall ceilings

Contract `member_plan_determinism_v1`. Capture `fpl-live-20260918T122516Z-cd5c04029774`, season 2026-27, gameweek 5, 15 members. Arms are wall ceilings in seconds: `wall_1s` at 1.0, `wall_2s` at 2.0, `wall_5s` at 5.0, `wall_30s` at 30.0, `wall_300s` at 300.0, `wall_1800s` at 1800.0. The deterministic budget is pinned at 20.0 in every arm, the value the planner uses in production, and is passed explicitly so the planner does not raise a low ceiling to its own default. Only the wall ceiling differs.

Descriptive. Nothing is promoted and no default moves.

## Did the published answer move?

- Members whose comparable record moved at any ceiling: **15 of 15**.
- Members whose published answer moved, meaning the squad, the eleven, the captain, the chip or the bench order a member reads: **5 of 15**.

| member | answer moved | fields that moved |
| --- | --- | ---: |
| 2199732 | no | 5 |
| 2281624 | no | 6 |
| 313686 | yes | 16 |
| 3832237 | yes | 16 |
| 4287206 | no | 5 |
| 5081114 | yes | 16 |
| 5349883 | no | 5 |
| 5662073 | no | 5 |
| 6654210 | yes | 16 |
| 6879786 | no | 5 |
| 6880255 | no | 5 |
| 7018833 | yes | 16 |
| 7252721 | no | 5 |
| 8548384 | no | 5 |
| 8883467 | no | 13 |

## What a cut tie-break did, as distinct from a cut search

| arm | tie-break cut by the clock | of those, answer moved |
| --- | ---: | ---: |
| `wall_1s` | 9 | 0 |
| `wall_2s` | 10 | 0 |
| `wall_5s` | 5 | 0 |
| `wall_30s` | 0 | 0 |
| `wall_300s` | 0 | 0 |
| `wall_1800s` | 0 | 0 |

**24 solves had their tie-break stopped by the clock and 0 of them published a different plan.** The tie-break is the phase that chooses between plans of equal objective value, and it is the mechanism this experiment was built around; on this capture, cutting it changed nothing a member reads.

Every cell whose answer did move was `FEASIBLE`, which is the ordinary case of a primary search stopped before it proved, not the subtle one. That is the more reassuring of the two readings and it is the better supported, so it is stated here rather than left for a reader to derive from the cells.

## What the clock cost, per arm

| arm | wall ceiling | solves | not proved | clock stopped the search | no week to publish | wall seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `wall_1s` | 1.0 | 15 | 6 | 15 | 0 | 17.1 |
| `wall_2s` | 2.0 | 15 | 4 | 14 | 0 | 31.8 |
| `wall_5s` | 5.0 | 15 | 2 | 7 | 0 | 62.3 |
| `wall_30s` | 30.0 | 15 | 0 | 0 | 0 | 137.0 |
| `wall_300s` | 300.0 | 15 | 0 | 0 | 0 | 132.7 |
| `wall_1800s` | 1800.0 | 15 | 0 | 0 | 0 | 133.7 |

Wall seconds are this machine's, measured while other work was running, and are not a claim about how long a solve takes on a quiet machine. Here the wall clock is the independent variable, so what it did is the subject and not the noise.

The ceiling moved something. The table below compares each arm against the reference, which is the widest ceiling, for the members whose published answer changed. Overlap counts the players in common with the reference plan, so 15 and 11 mean the same fifteen and the same eleven. The full plans are in the JSON; a squad is thirty names and does not belong in a table.

| member | arm | status | squad overlap | eleven overlap | captain | own points | bound gap |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: |
| 313686 | `wall_1s` | FEASIBLE | 12 of 15 | 7 of 11 | same | 53.74 | 10.174 |
| 313686 | `wall_2s` | FEASIBLE | 12 of 15 | 9 of 11 | same | 56.73 | 7.359 |
| 313686 | `wall_5s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 57.54 | 0.000 |
| 313686 | `wall_30s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 57.54 | 0.000 |
| 313686 | `wall_300s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 57.54 | 0.000 |
| 313686 | `wall_1800s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 57.54 | 0.000 |
| 3832237 | `wall_1s` | FEASIBLE | 6 of 15 | 3 of 11 | same | 47.50 | 56.578 |
| 3832237 | `wall_2s` | FEASIBLE | 11 of 15 | 7 of 11 | different | 50.53 | 13.329 |
| 3832237 | `wall_5s` | FEASIBLE | 11 of 15 | 7 of 11 | different | 50.67 | 13.191 |
| 3832237 | `wall_30s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 54.03 | 0.000 |
| 3832237 | `wall_300s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 54.03 | 0.000 |
| 3832237 | `wall_1800s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 54.03 | 0.000 |
| 5081114 | `wall_1s` | FEASIBLE | 12 of 15 | 8 of 11 | same | 55.23 | 8.776 |
| 5081114 | `wall_2s` | FEASIBLE | 13 of 15 | 9 of 11 | same | 55.40 | 8.439 |
| 5081114 | `wall_5s` | FEASIBLE | 15 of 15 | 11 of 11 | same | 55.75 | 8.042 |
| 5081114 | `wall_30s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 55.75 | 0.000 |
| 5081114 | `wall_300s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 55.75 | 0.000 |
| 5081114 | `wall_1800s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 55.75 | 0.000 |
| 6654210 | `wall_1s` | FEASIBLE | 14 of 15 | 11 of 11 | same | 56.74 | 7.288 |
| 6654210 | `wall_2s` | FEASIBLE | 15 of 15 | 11 of 11 | same | 56.74 | 6.795 |
| 6654210 | `wall_5s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 56.74 | 0.000 |
| 6654210 | `wall_30s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 56.74 | 0.000 |
| 6654210 | `wall_300s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 56.74 | 0.000 |
| 6654210 | `wall_1800s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 56.74 | 0.000 |
| 7018833 | `wall_1s` | FEASIBLE | 11 of 15 | 7 of 11 | same | 55.46 | 8.408 |
| 7018833 | `wall_2s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 55.61 | 0.000 |
| 7018833 | `wall_5s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 55.61 | 0.000 |
| 7018833 | `wall_30s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 55.61 | 0.000 |
| 7018833 | `wall_300s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 55.61 | 0.000 |
| 7018833 | `wall_1800s` | OPTIMAL | 15 of 15 | 11 of 11 | same | 55.61 | 0.000 |

The members whose answer did not move still show differences in the solver's own accounting at the low ceilings, which is the deterministic work spent and the bound reached rather than the plan chosen. Those are in the JSON under `per_member`.
