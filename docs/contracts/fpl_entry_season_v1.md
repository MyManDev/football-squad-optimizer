# FPL entry season v1

Refs #983 and the any-league parity program. Contract: `fpl_entry_season_v1`. The schema is
[`fpl_entry_season_v1.schema.json`](fpl_entry_season_v1.schema.json) and the synthetic example is
[`fpl_entry_season_v1.examples.json`](fpl_entry_season_v1.examples.json).

The FPL forwarder ([ADR 0012](../architecture/decisions/0012-fpl-forwarder.md)) answers
`GET /api/v1/fpl/entry/{entry}/season` with this document: one entry's season to date, read from
FPL's `entry/{entry}/history/` on the visitor's request and trimmed to the fields below. It is
never FPL's own JSON. The site reads it for a league its directory does not list, to build on the
device what the weekly run publishes for a listed league: each member's weekly net and total for
the scoreboard, the ranks for the race, and the actual side of the member's history.

The bundle (`fpl_entry_bundle_v1`) reads the same FPL history but keeps only what the device's
planner needs; a week's points are deliberately absent from it. This document is where they
are, so the two stay separate: a plan request reads the bundle, a scoreboard or history reads
the season.

## Fields

| Field | Meaning |
| --- | --- |
| `contract_version` | Exactly `fpl_entry_season_v1`. |
| `entry_id` | The entry asked for. FPL's `entry/{id}/history/` carries no identity of its own; a 404 names an entry FPL does not have. |
| `source_time` | When the forwarder read the history (UTC, ISO 8601, ending in `Z`). A last good copy keeps its original time. |
| `weeks` | One row per played gameweek, in gameweek order, no gameweek twice. |
| `chips` | Per chip played `name` and `event`, as the bundle's `history.chips`. |

Each week keeps nine of FPL's fields under FPL's names:

| Field | Meaning |
| --- | --- |
| `event` | The gameweek, 1 to 38. |
| `points` | The week's gross points, before the transfer hit. |
| `total_points` | The season total after this week, net of hits. |
| `rank` | FPL's rank for the week, or `null` where FPL gives none or a negative value. |
| `overall_rank` | The overall rank after this week, or `null` likewise. |
| `event_transfers` | Transfers made for the week. |
| `event_transfers_cost` | The hit paid for the week, 0 or more. |
| `bank` | The bank after the week in tenths, or `null` where FPL gives none. |
| `value` | The squad's value after the week in tenths, or `null` likewise. |

A row whose `event`, `points` or `total_points` is not an integer, or a gameweek that appears
twice, is treated as FPL failing (ADR 0012, decision 5), and the last good copy is served.

## How long a copy lives

As a bundle's: until the next deadline once the current week is finished, ten minutes while it
is still being played, and never past the next deadline, when a new week joins the history.
