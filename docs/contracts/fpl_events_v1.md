# FPL events v1

Refs #983 and the any-league parity program. Contract: `fpl_events_v1`. The schema is
[`fpl_events_v1.schema.json`](fpl_events_v1.schema.json) and the synthetic example is
[`fpl_events_v1.examples.json`](fpl_events_v1.examples.json).

The FPL forwarder ([ADR 0012](../architecture/decisions/0012-fpl-forwarder.md)) answers
`GET /api/v1/fpl/events` with this document: each gameweek's state and the game's average and
highest score, read from FPL's `bootstrap-static/` on the visitor's request and trimmed to the
fields below. It is the one document the forwarder reads from the bootstrap, and nothing else of
the bootstrap (players, clubs, prices, fixtures) leaves the Worker: the weekly run publishes what
the device needs of those. The site reads it for a league its directory does not list, for the
game average and the highest score its scoreboard shows beside the members' own.

## Fields

| Field | Meaning |
| --- | --- |
| `contract_version` | Exactly `fpl_events_v1`. |
| `source_time` | When the forwarder read the bootstrap (UTC, ISO 8601, ending in `Z`). A last good copy keeps its original time. |
| `events` | One row per gameweek FPL lists, in gameweek order, no gameweek twice. |

Each event keeps five of FPL's fields under FPL's names:

| Field | Meaning |
| --- | --- |
| `id` | The gameweek, 1 to 38. |
| `finished` | FPL's `finished`: every fixture of the week has been played. |
| `data_checked` | FPL's `data_checked`: the week's points are final. |
| `average_entry_score` | The game's average score for the week, 0 before it is played. |
| `highest_score` | The game's highest score for the week, or `null` before it is played. |

## How long a copy lives

One hour. The averages move only while a week is played, and the week's state changes a few
times a week; the bootstrap is FPL's largest document, so it is read as rarely as that allows.
