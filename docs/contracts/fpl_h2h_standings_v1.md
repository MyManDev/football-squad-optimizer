# FPL head-to-head league standings v1

Refs the any-league parity program (every league works as the published one). Contract:
`fpl_h2h_standings_v1`. The schema is
[`fpl_h2h_standings_v1.schema.json`](fpl_h2h_standings_v1.schema.json) and the synthetic
example is [`fpl_h2h_standings_v1.examples.json`](fpl_h2h_standings_v1.examples.json).

The FPL forwarder ([ADR 0012](../architecture/decisions/0012-fpl-forwarder.md)) answers
`GET /api/v1/fpl/h2h/{league}/standings?page={page}` with this document: one page of one
head-to-head league, read from FPL's `leagues-h2h/{league}/standings/?page_standings={page}` on
the visitor's request and trimmed to the fields below. It is never FPL's own JSON. The site
reads it for a head-to-head league its directory does not list, as it reads
`fpl_league_standings_v1` for a classic one: page 1 when the league's address is opened, then
only the page the visitor requests. A classic league asked for here is refused as
`classic_league`, so the site asks for its classic standings instead.

## Fields

| Field | Meaning |
| --- | --- |
| `contract_version` | Exactly `fpl_h2h_standings_v1`. |
| `league.id` | The league asked for. FPL's answer must declare it, or the answer is not read. |
| `league.name` | The league's name as FPL states it, or `null` when it states none. |
| `league.scoring` | Exactly `h2h`. |
| `page` | The page asked for, 1 to 1000. FPL's answer must be that page. |
| `has_next` | FPL's `has_next`: whether a further page exists. |
| `source_time` | When the forwarder read the page (UTC, ISO 8601, ending in `Z`). A last good copy keeps its original time. |
| `results` | The page's rows in FPL's order. |

Each row keeps twelve of FPL's fields under FPL's names:

| Field | Meaning |
| --- | --- |
| `entry` | The member's entry id. No entry appears twice on a page. |
| `entry_name`, `player_name` | The team's name and the manager's name, as text. |
| `rank` | The rank FPL shows, 0 or more. |
| `rank_sort` | FPL's total order, from 1. Consecutive pages continue it. |
| `last_rank` | The previous rank as FPL gives it, or `null`. |
| `total` | Head-to-head points: three a win, one a draw. |
| `matches_played`, `matches_won`, `matches_drawn`, `matches_lost` | The record so far. |
| `points_for` | The member's FPL points over the season, what a classic table calls `total`. |

## How long a copy lives

Ten minutes, as a classic standings page.
