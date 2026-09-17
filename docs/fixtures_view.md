# Fixture list

`application.build_site` writes `data/fixtures.json` beside `data/index.json` whenever it
is given a capture, which is the same verified `CapturedSnapshot` the league comparison
and the provisional score already read. `scripts.build_site` and the weekly runner's site
stage therefore both produce it; `--no-league` reads no capture and publishes none. No new
upstream collection, endpoint, worker or scheduling is involved.

The document uses the separate, closed `fixtures_v1` contract
(`docs/contracts/fixtures_v1.schema.json`, shipped as `data/schema/fixtures_v1.schema.json`).
`ui_view_v1` is unchanged.

## What it states

- `season`, named from the capture's own first deadline, with `source_snapshot_id` and
  `captured_at_utc`.
- `current_gameweek`: the first gameweek whose deadline the capture instant had not
  reached (`next_open_deadline`, the rule the league views target a week by). Null once no
  deadline is open.
- `gameweeks`: every gameweek the capture's event list publishes, each with its
  `deadline_utc` and its fixtures sorted by kickoff, then fixture id. A gameweek with no
  fixture is published with an empty list.
- Per fixture: `fixture_id`, `kickoff_utc`, `home` and `away` (`team_id`, `name`,
  `short_name`, resolved through the same capture), `finished`, `home_score`, `away_score`.
- `unscheduled_count`: fixtures the payload holds with no gameweek. They are counted and
  not listed, because no gameweek holds them.

It carries schedule and results only: no projection, no difficulty figure, no expectation
about a match.

## Absent is not zero

A fixture without a kickoff publishes a null `kickoff_utc`. Scores are null unless the
payload states both; a goalless draw is `0` and `0`, an unplayed match is null and null.
Before full time a stated score is the score at the capture, so the page shows a score
only beside `finished`.

A capture without the bootstrap or the fixtures payload publishes no file. So does a
capture of another season, whose week numbers would sit wrongly beside this season's
pages, and a capture whose fixture list cannot be read: the build says so on stdout and
writes the week's other views as usual. Nothing is backfilled from an older capture.

## The page

On a wide screen the shell shows `current_gameweek` in the left margin and the gameweek
after it in the right margin; on a narrow one the same two lists sit closed under the
page. `/fixtures` lists both and then every earlier gameweek, newest first. None of this
keeps state: when a later capture names a later `current_gameweek`, next week becomes this
week, a new week appears as next, and the week that was current joins the archive.

A published tree with no `data/fixtures.json` renders no panels and no error.
