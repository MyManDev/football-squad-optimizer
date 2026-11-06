# FPL league standings v1

Refs #980 and #983. Contract: `fpl_league_standings_v1`. The schema is
[`fpl_league_standings_v1.schema.json`](fpl_league_standings_v1.schema.json) and the synthetic
examples are [`fpl_league_standings_v1.examples.json`](fpl_league_standings_v1.examples.json).

The FPL forwarder ([ADR 0012](../architecture/decisions/0012-fpl-forwarder.md)) answers
`GET /api/v1/fpl/standings/{league}?page={page}` with this document: one page of one classic
league, read from FPL's `leagues-classic/{league}/standings/?page_standings={page}` on the
visitor's request and trimmed to the fields below. It is never FPL's own JSON. Since #983 step 4
the site reads it for a league its directory does not list (`web/src/features/league/forwarded/`):
page 1 when the league's address is opened, and each next page as the visitor scrolls.

## Fields

| Field | Meaning |
| --- | --- |
| `contract_version` | Exactly `fpl_league_standings_v1`. |
| `league.id` | The league asked for. FPL's answer must declare it, or the answer is not read. |
| `league.name` | The league's name as FPL states it, or `null` when it states none. |
| `league.scoring` | Exactly `classic`: the route reads classic standings only, and a head-to-head league is refused. |
| `page` | The page asked for, 1 to 20. FPL's answer must be that page. |
| `has_next` | FPL's `has_next`: whether a further page exists. On page 20 it says the league has more than the device reads. |
| `last_updated_data` | FPL's `last_updated_data` as text, or `null` when absent or blank. Pages of one league read together should share it, as the capture's reader requires. |
| `source_time` | When the forwarder read the page (UTC, ISO 8601, ending in `Z`). A last good copy keeps its original time. |
| `results` | The page's rows in FPL's order. |

Each row keeps eight of FPL's fields, under FPL's names, so a port of the Python reader
(`fpl_league_standings_page` in `src/squadopt/data/sources/fpl_live.py`) reads it unchanged:

| Field | Meaning |
| --- | --- |
| `entry` | The member's entry id. No entry appears twice on a page. |
| `entry_name`, `player_name` | The team's name and the manager's name, as text. |
| `rank` | The rank FPL shows, 0 or more. |
| `rank_sort` | FPL's total order, from 1. Consecutive pages continue it. |
| `last_rank` | The previous rank as FPL gives it, or `null`. The Python reader reads 0 as unavailable too. |
| `total` | Total points. |
| `event_total` | The latest week's points. |

## Refusals

Every refusal is JSON with `x-squadopt-fpl: 1`, never this document:

- a page above 20, a league id that is not a positive integer, or a query other than `page`:
  404 `not_found`, with FPL asked nothing;
- FPL has no classic page 1 for the id and its head-to-head table declares the league: 404
  `head_to_head_league`, naming the league;
- FPL has no classic page 1 and no head-to-head table for it: 404 `league_not_found`;
- FPL has no such later page: 404 `page_not_found`;
- FPL refuses or fails and no last good copy is held: 503 `upstream_unavailable`.

## Copies

A page is kept for 10 minutes in the serving data centre, and its last good copy for two days
longer; a refusal for a league or page FPL does not have is kept for 10 minutes. The forwarder
serves the last good copy, unchanged, with `x-squadopt-fpl-cache: last-good`, when FPL answers
429 or 5xx, cannot be reached, or sends an answer this contract cannot be read from.

## Synthetic examples

`fpl_league_standings_v1.examples.json` holds two pages of one invented league,
`first_page` with `has_next` true and `last_page` without. The forwarder's node tests build them
from synthetic FPL-shaped answers and require the result to equal the file;
`tests/unit/test_fpl_forwarder_contracts.py` validates them against the schema.
