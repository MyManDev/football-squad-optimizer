# Live data source options for the 2026-27 deadline snapshot

Status: **decided on 2026-08-13**. Option A is the capture path and Option B is retained as an
independent cross-check. The findings below are what was verified on that date and are kept
so the decision can be re-examined against evidence rather than recollection.

The terms-of-use reading in Option A is the part of this decision that is a judgement rather
than a technical finding. It was made by the data owner with that tension stated, and the
posture it commits to — local gitignored snapshots, private and non-commercial use, nothing
published or redistributed — is binding on every implementation that follows.

The historical archive pinned at `vaastav/Fantasy-Premier-League@8c97b2a` is post-hoc:
it publishes a gameweek after it has been played. Producing a squad for an upcoming
deadline needs a source that is readable *before* that deadline, which the archive's
gameweek files are not. That gap is the only reason this document exists.

## What the snapshot has to deliver

The live source is not free to provide whatever it likes. Its output has to satisfy
contracts that are already frozen elsewhere in this repository.

| Requirement | Where it comes from | Why it is not negotiable |
| --- | --- | --- |
| Persistent `player_id` equal to the archive's `code` | `docs/data_contract.md` | Cross-season carry-over and the residual history join on it |
| Integer `price_tenths` | canonical contract | A single missing value turns the column to float and the optimizer rejects the table |
| Controlled `position` in GK / DEF / MID / FWD | canonical contract | Squad and formation constraints are expressed over it |
| `team_id` in the same identifier space as fixtures | fixture contract | Team-level shocks in the scenario generator group on it |
| A deadline timestamp for the target gameweek | `fixture_snapshot_v1` | Live mode has to resolve "the next deadline that has not closed" |
| Fixture rows per team per fixture | `fixture_snapshot_v1` | Double gameweeks have no single correct player-gameweek value |
| A capture timestamp we control | `fixture_snapshot_v1` | Leakage safety for availability depends on proving capture preceded the deadline |

## Option A — the Premier League's own Fantasy endpoints, captured by us

Two unauthenticated JSON endpoints under `https://fantasy.premierleague.com/api/`:
`bootstrap-static/` and `fixtures/`. Both were read on 2026-08-13 and the field
inventory below is observed, not documented.

`bootstrap-static/` returns top-level `events`, `teams`, `elements`, `element_types`,
`element_stats`, `phases`, `chips`, `game_settings`, `game_config`, `total_players`.

- `events[]` carries `id`, `deadline_time`, `deadline_time_epoch`, `is_next`,
  `is_current`, `is_previous`, `finished`, `data_checked`, `released`. The entry with
  `is_next: true` was Gameweek 1 with `deadline_time` `2026-08-21T17:30:00Z`.
- `elements[]` carries `code` and `id` as separate fields, plus `team`, `team_code`,
  `element_type`, `now_cost`, `status`, `chance_of_playing_this_round`,
  `chance_of_playing_next_round`, `news`, `news_added`, `selected_by_percent`,
  `first_name`, `second_name`, `web_name`, `can_select`, `removed`.
- `teams[]` carries `id`, `code`, `name`, `short_name`, `strength`, and the six
  directional strength fields (`strength_overall_home`/`_away`,
  `strength_attack_home`/`_away`, `strength_defence_home`/`_away`).

`fixtures/` returns 380 fixture objects carrying `id`, `code`, `event`, `team_h`,
`team_a`, `team_h_difficulty`, `team_a_difficulty`, `kickoff_time`, `finished`,
`finished_provisional`, `started`, `provisional_start_time`, `minutes`, `pulse_id`.

### What this option satisfies

Every row of the requirements table. `code` is the archive's persistent identifier, so
the cross-season join works without a name-matching heuristic. `now_cost` is already in
tenths. `element_type` maps to the controlled position vocabulary. `events[].is_next`
plus `deadline_time` is exactly what live mode needs to resolve the target gameweek.
`fixtures/` is already at team-fixture grain once each object is expanded into its home
and away rows, which is the grain `fixture_snapshot_v1` specifies.

It also uniquely fixes the availability timing problem. `status`,
`chance_of_playing_next_round` and `news_added` are unusable as features when read from
the archive, because the archive records them after the fact and their as-of time cannot
be recovered. When *we* capture them and stamp `captured_at_utc` ourselves, the timing is
provable for every gameweek from now on. That does not retroactively make historical
availability usable, so it changes the future, not the training set.

### What this option costs

- **No official documentation and no published contract.** The field inventory above is
  observed behaviour. Fields can be added, renamed or removed without notice, so the
  adapter has to validate its input and fail loudly rather than assume a shape.
- **No published rate limit.** Excessive requests return HTTP 429. Two endpoint reads per
  deadline is far below any plausible threshold, but the fetch must be a deliberate
  manual step and must never run in CI.
- **No `robots.txt` is served** for the host; the path returns the application shell.
  There is therefore no machine-readable crawl directive either permitting or forbidding
  the request.

### Terms of use — read this before deciding

The Premier League's terms of use were checked on 2026-08-13. They contain no clause
naming scraping, robots, data mining or automated access. They do contain two clauses
that bear directly on this decision:

> "You may download and print material from the Website or App as is reasonable for your
> own private and personal use"

> "The Website and App must not be used in any other way, including for commercial
> purposes, and you may not otherwise reproduce, re-utilise or redistribute it
> (including, by way of example, creating a database (electronic or otherwise) that
> includes material downloaded or otherwise obtained from the Website or App)"

Read strictly, private and personal use is permitted and redistribution is not — and the
parenthetical names database creation as an example of what is not permitted. Storing
snapshots on disk is therefore in tension with that clause on a strict reading, even
though the practice is widespread in the community. Widespread practice is not permission.

This is a factual reading of the clause, not legal advice, and the call belongs to the
data owner. What follows from it is a posture, not a workaround:

- Snapshots stay local and gitignored, exactly as `data/raw/` already is. The repository
  carries checksums and synthetic samples only.
- The project stays private and non-commercial. If that ever changes, this source has to
  be replaced by a licensed one before the change ships, not after.
- No snapshot is published, shared or served, and no derived database is redistributed.

This is the same posture already adopted for the archive, where the licence covers the
code and not the data. The option therefore adds no new *category* of risk. It does
extend an existing one, which is why it is stated plainly here rather than buried.

## Option B — the archive's 2026-27 pre-season files, on a new pin

The archive already carries `data/2026-27/` containing `players_raw.csv`,
`fixtures.csv`, `teams.csv`, `player_idlist.csv` and a `players/` directory. There is no
`gws/` directory yet, which is consistent with no gameweek having been played.

`players_raw.csv` is a dump of the same `elements` payload as Option A, so the field
coverage for roster, price and position is broadly equivalent, and `fixtures.csv` covers
the fixture list. Pinning a new archive commit keeps one adapter, one licence story and
byte-identical inputs for every team member.

### Why it cannot carry live mode on its own

- **No capture timestamp.** The files do not record when the scrape ran. Prices move
  daily and availability moves hourly near a deadline, so a snapshot whose as-of time is
  unknown cannot be proven to precede the deadline. That is the precise property
  `fixture_snapshot_v1` requires.
- **No control over freshness.** The pin is a commit, not a time. A commit taken three
  days before the deadline yields three-day-old prices, and we would not be able to tell.
- **No deadline field.** `fixtures.csv` has `kickoff_time`, but the FPL deadline is a
  separate quantity roughly ninety minutes before the first kickoff and is published in
  `events`, which these files do not contain. Live mode cannot resolve its own target.

## Option C — third-party sports data providers

Commercial providers such as API-Football and Sportmonks publish match, lineup and
advanced-statistic feeds under explicit commercial licences, which is a genuinely better
legal footing than either option above.

They cannot satisfy this contract. FPL price, FPL position and the FPL `code` are
artefacts of the fantasy game, not of football, and no general football data provider
publishes them. An optimizer that must spend the price actually payable at the deadline
cannot be fed a source that does not know that price. These providers are therefore a
possible later *complement* for signals the FPL data lacks, such as shot-level expected
goals, and not a substitute for the snapshot.

## Recommendation

Adopt Option A as the capture path and keep Option B as an independent cross-check.

Option A is the only option that satisfies the frozen contracts, and its capture
timestamp is what makes availability usable as a documented inference rule going forward.
Reproducibility is preserved without redistribution: every capture is written once as an
immutable local snapshot carrying `snapshot_id`, `captured_at_utc`, source identifier,
checksum and schema version, so any past decision can be replayed exactly from disk while
the repository still holds no real data.

Option B costs little as a cross-check. When a new archive pin covering 2026-27 exists,
comparing its roster prices and positions against our own snapshot detects an adapter
that has silently drifted from the source everyone else reads.

The terms-of-use tension above is the part of this recommendation that is a judgement
call rather than a technical finding, and it is the reason the choice is not mine to make.
