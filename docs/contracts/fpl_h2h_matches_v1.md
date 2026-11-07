# FPL head-to-head league matches v1

Refs the any-league parity program (every league works as the published one). Contract:
`fpl_h2h_matches_v1`. The schema is
[`fpl_h2h_matches_v1.schema.json`](fpl_h2h_matches_v1.schema.json) and the synthetic example
is [`fpl_h2h_matches_v1.examples.json`](fpl_h2h_matches_v1.examples.json).

The FPL forwarder ([ADR 0012](../architecture/decisions/0012-fpl-forwarder.md)) answers
`GET /api/v1/fpl/h2h/{league}/matches?gw={gameweek}&page={page}` with this document: one page of
one head-to-head league's pairings for one gameweek, read from FPL's
`leagues-h2h-matches/league/{league}/?page={page}&event={gameweek}` on the visitor's request and
trimmed to the fields below. It is never FPL's own JSON. The site reads it for a head-to-head
league its directory does not list: the week's pairings on the league page, and a member's
opponent of the week, who is the rival a rival strategy is played against unless the member
names another.

The gameweek runs from 1 to the week after the latest started one, which is the week the
pairings are known for; a later one is refused with 404 before FPL is asked anything.

## Fields

| Field | Meaning |
| --- | --- |
| `contract_version` | Exactly `fpl_h2h_matches_v1`. |
| `league.id` | The league asked for. |
| `league.scoring` | Exactly `h2h`. |
| `gameweek` | The gameweek asked for, 1 to 38. Every match FPL answers must be of it. |
| `page` | The page asked for, 1 to 1000. FPL's answer must be that page. |
| `has_next` | FPL's `has_next`: whether a further page exists. |
| `source_time` | When the forwarder read the page (UTC, ISO 8601, ending in `Z`). A last good copy keeps its original time. |
| `results` | The page's matches in id order. No match appears twice. |

Each match keeps:

| Field | Meaning |
| --- | --- |
| `id` | FPL's match id. |
| `entry_1`, `entry_2` | Each side: `entry` (the entry id, or `null` for the league average or a bye), `name`, `player_name` and `points`, the side's score for the week as FPL states it so far. |
| `winner` | The winning entry id once FPL has decided the match, or `null`. |
| `started`, `finished` | FPL's flags for the week's play, or `null` where FPL gives none. |

## How long a copy lives

Ten minutes, as a standings page: a match's points move while the week is played.
