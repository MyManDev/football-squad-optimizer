# Football forecast reliability by lead: protocol

Status: pre-registered, written before any of its forecasts is made. It declares a
measurement, not a candidate. It changes no forecast, planner, default, member page or
capture, and it promotes nothing. Its question is the prediction side's
(`docs/architecture/ownership.md`): how much the football forecast `football_team_share_v1`
loses per week of lead. Nothing is run by this document. Its runner is a separate pull request, and the run
waits until this protocol has merged.

## Why this is written

A planner's horizon should rest on how its forecast degrades with lead
(`docs/prediction_research_agenda.md`, "Multi-horizon forecasting"). For
`football_team_share_v1`, the football model the experimental option has served so far, no
such record exists:

- `horizon_decay` (`src/squadopt/backtest/horizon_decay.py`) measures the drift of the
  earlier horizon builder, not the football model, at offsets 0 to 3 by default.
- #880 (`docs/research/football_window_totals.md`) measured the summed error of 1, 3 and 5
  week windows. A summed error mixes leads and cannot be compared across window lengths, as
  that record says.

This protocol measures the error at each lead separately, for `football_team_share_v1`
only, from one to fourteen weeks ahead. The joint role model the owner is preparing for the
experimental option (`football_joint_role_minutes_v1`) is a different model; a record of it
needs its own protocol, and this one says nothing about it.

## What has been read

- 2022-23 supplies priors only: `causal_training` in
  `src/squadopt/application/football_live.py` skips the first archive season.
- 2024-25 is reused. It was a development season of the football candidate
  (`docs/research/football_candidate_results.md`), and #880 scored its five-week forecasts
  from GW11, 15, 19, 23, 27 and 31, so its leads 1 to 5 from those origins have been read.
  Its leads 6 to 14 have not.
- 2023-24 is reused too. It was the inner validation season of the component ablation
  (`docs/research/football_component_ablation.md`), and its archive files are hashed in later
  football records.
- No evaluation season here is unread, so the record is descriptive development evidence
  and claims no confirmation.
- 2025-26 is never opened. The owner's 2026-09-28 scope
  (`docs/research/football_defcon_development_scope.md`) would allow it as development data;
  this protocol does not use that permission. No 2025-26 file is listed, hashed or read.

## Seasons and origins

- The evaluated seasons are 2023-24 and 2024-25. The history is
  `archive_history(root, seasons=("2022-23", "2023-24", "2024-25"))` from
  `src/squadopt/data/sources/football_history.py`, which never opens an excluded season.
- The **measured origins** are GW11, 15, 19, 23, 27 and 31 of each season, the origins of
  `scripts/measure_football_contextual.py` and #880. A measured origin o forecasts gameweeks
  o through o + 13, or through GW38 when that comes first: fourteen weeks from GW11 to GW23,
  twelve from GW27 and eight from GW31.
- The **lead** of a target gameweek g from origin o is g - o + 1.
- The **lead-1 origins** are every gameweek from GW11 to GW38 of each season, and they are
  used for lead 1 only. The reason: four weeks apart, a target gameweek forecast at lead k
  from a measured origin is itself a measured origin only when k is 1, 5, 9 or 13. A
  comparison with lead 1 would then exist at three leads and not at the others.

## Decision instant, fit and roster

- The **decision instant** of an origin is the earliest `kickoff` of the archive's rows of
  that gameweek, less 90 minutes, as in `scripts/measure_football_contextual.py`.
- The **history** of a fit is the selected archive's rows whose kickoff is more than three
  hours before the decision instant, the rule `causal_training` applies to its own features.
- The **training rows** are `causal_training` of the selected archive, computed once. Each
  fit keeps the rows whose kickoff is more than three hours before its decision instant. That
  is the same set `causal_training` returns on the fit's own history: each row's features are
  computed at its own gameweek's first kickoff, from history settled before it.
- The **model** is `FixtureFootballModel` from `src/squadopt/prediction/football.py`,
  unchanged, fitted with `cutoff` at the decision instant. No setting is tuned.
- The **roster** of an origin o is every player with an archive row in gameweek o - 1 or
  o - 2 of the same season whose kickoff is more than three hours before the decision instant.
  The club, position, name, team and price (`value`) come from that player's latest such
  row.
  - Two weeks, so that a club's single blank week does not remove its players.
  - Nothing after the decision instant decides who is in the roster. A forecast fourteen
    weeks ahead cannot know who plays then. The earlier rule `phase_c_decision_roster_v1`
    (`scripts/export_component_oof.py`) takes the target week's own rows, and this protocol
    does not use it.
  - The rule's limitation: a player who arrives after his origin is absent, and a player who
    leaves stays in the roster, his later fixtures unmatched and counted.
  - If a selected season's rows lack a column this rule names, the run stops before any fit
    and says which.
- The **calendar** is the archive's final calendar from each season's `fixtures.csv`
  (`event`, `kickoff_time`, `team_h`, `team_a`), as `scripts/measure_football_contextual.py`
  builds it. A fixture without an event is dropped and counted.
- Each origin is forecast by `build_football_horizon` in
  `src/squadopt/live/football_horizon.py`, with the origin's gameweeks, the fit's history and
  `captured_at` at the decision instant.

## What is forecast and matched

Each player-fixture forecast is matched to the archive's realized `total_points` by season,
fixture and player code. The error of a forecast is its `expected_points` less the realized
points. An unmatched player-fixture is unknown, never zero, and is counted by origin and
lead.

## Quantities

**Primary,** for each lead k from 2 to 14:

- Take every player-fixture forecast at lead k from a measured origin whose target gameweek
  g is also forecast, for the same player and fixture, at lead 1 from the lead-1 origin g.
- Its paired difference is e_k^2 - e_1^2.
- The unit is the target gameweek within a season, and its value is the mean paired
  difference over its player-fixtures. The lead's figure is the mean over its units.
- The figure's interval is `season_aware_moving_block_interval` from
  `src/squadopt/evaluation/statistics.py`, with the units of each season ordered by target
  gameweek. It uses these PromotionPolicy values, stated explicitly: confidence 0.90, 5000
  resamples, blocks of 4, seed 0, with `candidate_id` `lead_k` for lead k.
- A lead with fewer than six units is reported with its interval marked thin. Leads 13 and
  14 have at most four units in each season.
- The record also reports the mean of e_k^2 and the mean of e_1^2 behind each difference.

**Secondary,** descriptive, by lead, over the measured origins' forecasts:

- the mean signed error;
- the slope of realized on forecast points, by ordinary least squares;
- the within-position Spearman rank correlation of forecast and realized points, pooled over
  the lead's player-fixtures;
- top-ten optimism: forecast less realized points among each position's ten highest
  forecasts at each origin and target gameweek;
- counts of forecast, matched, unmatched and paired player-fixtures.

## Kept apart

- Target gameweeks in which any club has a blank or a double in the final calendar are
  reported separately and do not enter the primary quantity. The final calendar knows them
  in hindsight.
- A fixture moved after an origin cannot be told apart. `archive_history` reads only
  `team_h` and `team_a` from `fixtures.csv`, and that file carries final values, so the
  primary quantity may contain such fixtures. The record says so.

## Records and runner

- The record is `docs/research/football_lead_reliability.json`, with its markdown twin and a
  row in `docs/measurements_index.md` (`docs/architecture/decisions/0003-measurement-artifacts.md`).
- The record names:
  - the repository commit;
  - the hashes of the three seasons' archive files;
  - the seasons loaded;
  - the decision instant of every origin;
  - every failed origin with its error;
  - `seasons_never_opened: ["2025-26"]` and `locked_holdout_accessed: false`.
- Per-fixture forecasts and labels stay in the run's output directory and are never
  committed.
- The runner is `scripts/measure_football_lead_reliability.py`, tested on synthetic frames.
  - Its `check` command hashes the three seasons' archive files and confirms the columns
    this protocol names, before anything is fitted.
  - Its `measure` command writes into a fresh directory outside the repository's `data/` and
    `docs/`.
- It runs once, on the machine that holds the archive, as one heavy job and never during a
  weekly run. It reads no capture, member data or live store.
- A failed origin is recorded and never rerun with other settings.

## What a result licenses

Nothing by itself. The record does not choose a planner horizon, does not lengthen the
served artifact and says nothing about the contextual model, the joint role model or the
current model. A
lead-dependent dispersion or shrinkage needs its own protocol, declared after this record.

## Deliberate exclusions

- No 2025-26, no candidate, no tuning and no promotion.
- No capture, member document, live store or outcome store.
- The calendar and the roster are reconstructed from the archive, not deadline snapshots.
  The record calls them that, as the earlier football records do.
