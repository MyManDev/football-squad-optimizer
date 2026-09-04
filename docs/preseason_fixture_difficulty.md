# What the platform published about 2026-27 before it started

- Contract `preseason_difficulty_record_v1`; capture `fpl-live-20260816T081259Z-e44ade0095e5` from `fpl-live`, taken **2026-08-16T08:12:59Z**.
- First kickoff **2026-08-21T19:00:00+00:00**, first deadline **2026-08-21T17:30:00Z** — the capture precedes the first kickoff by **130.8 hours**, and the record refuses to be built from a capture that does not.
- 380 fixtures across 38 gameweeks, 20 clubs, 760 fixture sides, 0 without a published rating.
- Snapshot fingerprint `e44ade0095e51f7c…`; payload checksums are recorded in the JSON beside this file, so an edited capture cannot be passed off as this one.

## Published difficulty, as it stood

| Rating | Fixture sides |
| --- | ---: |
| 2 | 209 |
| 3 | 342 |
| 4 | 171 |
| 5 | 38 |

## What the platform did *not* publish yet

Team strength is a separate field from fixture difficulty, and before a season it is largely empty. Fields carrying a non-zero value for at least one club:

| Field | Clubs with a non-zero value |
| --- | ---: |
| `strength` | 0 of 20 |
| `strength_overall_home` | 20 of 20 |
| `strength_overall_away` | 20 of 20 |
| `strength_attack_home` | 0 of 20 |
| `strength_attack_away` | 0 of 20 |
| `strength_defence_home` | 0 of 20 |
| `strength_defence_away` | 0 of 20 |

That asymmetry is evidence in its own right. A completed season's archive carries populated attack and defence numbers on a thousand-point scale; before a season the same fields are zero and only a coarse one-to-five overall rating exists. Whatever the archive's strength columns are, they are not what was published in August.

## Drift against a later reading

- 760 fixture sides compared, 0 not found in the later table.
- **0 changed** (0.0%), mean absolute change 0.00.

The published difficulty has not moved since it was recorded.

