# Data Layer Follow-up Work

Known gaps in the Sprint 0 data layer, with the reasoning behind each deferral.
Everything here was left out deliberately, not overlooked. Sprint 0's goal was a
working, tested, deterministic skeleton; these items make it *better*, not
*working*.

Items are grouped by who has to decide. The first group is filed as issues, the
second is data-layer work, and the third needs agreement with the optimization or
software owner before anyone starts.

## Tracked as GitHub issues

The two Sprint 1 items that started this list were done and their issues are closed:
the walk-forward split helper (#6) and the price-based prior for a player's opening
gameweek (#7, contract `opening_price_prior_v1`). The open part of item 1 is tracked in
#531. Item 11, a shared contracts module, was delivered as `squadopt.contracts` and is
enforced by the import-linter layers in `pyproject.toml`, so it has left this file; the
other numbers are kept because code and records cite them.

When one of the items below becomes real work, open an issue for it and delete it
from this file, so there is only ever a single record of it.

## Data layer

### 1. Expected minutes as its own model

**Now.** Expected minutes is a shifted rolling mean of past minutes. That is fine
for a steady starter and wrong for the cases that matter most: a player returning
from injury, or one newly promoted into the starting eleven, is projected from a
history that no longer describes them.

Because the baseline is `points_per_90 * expected_minutes / 90`, an error here
propagates directly into every projection.

The experiment contract assigns this to us explicitly: its `form_window` section
states that the prediction pipeline owns minimum-history behaviour, missing
matches, and window alignment.

**Proposal.** A start-probability signal combined with a minutes-given-start
estimate. `starts` is the natural input when a source provides it.
`availability_status` would help, but only after its snapshot timing is verified —
see item 3.

**Status: partly delivered; the rest is #531.** The live component base separates the
chance of any appearance from the minutes given an appearance
([component evaluation](phase_c_component_evaluation.md)). A start probability,
`q_start_given_appearance`, is fitted and calibrated in the mean
([participation calibration](participation_calibration.md)) but is not on the live path, and
composing the points side through it bought no accuracy
([participation composition](participation_composition.md)). The three-state participation
model, and the double-reduction question to settle before it, are tracked in #531.

### 2. Partial optional columns

**Now.** An optional column that is present must be complete; a column with any
missing value is rejected.

This is not pedantry. One missing value promotes an integer column to float, the
optimizer checks `price_tenths` element-wise against `numbers.Integral`, and the
whole projection table then gets refused far from the real cause. Nullable dtypes
and `pd.NA` fail the same way.

**Proposal.** A per-column missing-value policy in configuration, so a source with
patchy `expected_goals` coverage can be used without weakening the guarantees on
required columns. Real historical data will force this immediately.

Note that the experiment contract requires all candidate configurations in a
comparison to share an identical missing-data policy, so this policy has to be part
of the recorded configuration rather than an implicit default.

### 3. Columns with unverified timing

**Now.** `selected_by_percent` and `availability_status` sit in
`AMBIGUOUS_TIMING_COLUMNS` and are excluded from features. Both change
continuously up to a deadline, and a historical snapshot of either is often
recorded after the fact — which would make them post-match data disguised as
pre-match data.

`is_outcome_column()` treats unverified timing as outcome timing, so the
conservative answer is the current default.

**Proposal.** Inspect a real source, document when each value was actually
captured, and move each column into `PRE_MATCH_COLUMNS` or `OUTCOME_COLUMNS`
accordingly. Until that inspection happens, excluding them is the only defensible
choice.

**Status: resolved, and the two sources answer differently.** The inspection has now
happened on both paths, and the outcome is not one classification but two.

*The live path is verified pre-deadline.* The capture, taken by `squadopt season tick`
since the legacy shell was retired in #702, records
`status` and `chance_of_playing_this_round` together with an explicit `captured_at_utc`
that `normalize_utc_timestamp` refuses unless it is timezone-aware UTC, and the capture is
immutable and checksummed. Capture-before-deadline is provable rather than assumed, which
is what `captured_availability_rule_v1` rests on. Availability therefore reaches a live
decision as post-processing on a projection, never as a feature — the distinction that
keeps it out of the fitted model while still letting it zero an unavailable player.

*The archive path is verified post-hoc, permanently.* Measured against the pinned archive:
`players_raw.csv` is one snapshot per season and its latest `news_added` falls after that
season's final kickoff in all five seasons — 2021-22 at 2022-05-21T14:00Z against a final
kickoff of 2022-05-22T15:00Z, and the same shape in 2022-23, 2023-24, 2024-25 and 2025-26.
`gws/merged_gw.csv` carries no availability column at all. So the archive's availability is
the end-of-season state, nine months after an opening deadline, and using it as a
historical feature would leak the rest of the season into the decision.

The conclusion for `AMBIGUOUS_TIMING_COLUMNS` is therefore to keep `availability_status`
excluded from historical features **on evidence rather than caution**, while the live rule
consumes the captured value as post-processing. `selected_by_percent` was not inspected;
it stays excluded on the original conservative grounds and is a separate question.

Full measurement and its consequences: [GW1 evidence blocker
report](gw1_blocker_report_2021-2026.md), sections 2 to 5.

### 4. Fixture context features

**When this was written** (Sprint 0), `opponent_team_id`, `is_home` and
`fixture_difficulty` were classified as pre-match and carried through when present, no
feature used them, and the synthetic sample did not contain them. The classification still
stands in `PRE_MATCH_COLUMNS` (`src/squadopt/data/schema.py`); what uses the fixture
context now is in the status below.

**Proposal.** Opponent strength and home advantage adjustments, once a verified
source supplies them. `fixture_difficulty` is only usable if the source's rating is
genuinely pre-match rather than computed afterwards. Nothing here may be fabricated
to make the feature set look richer.

The experiment contract adds a requirement beyond mere availability: fixture
information must be versioned as it was known at each decision timestamp. A single
current-value fixture table is not sufficient for backtesting.

**Status: this item has split into three, and "no feature uses them" is no longer true of
any of them in the same way.**

*Calendar-derived features are in use.* `attach_fixture_features` produces `fixture_count`
and `home_fixture_count` (the latter derived from `is_home`). Two places read both: the
Phase C component base, the live default since #351, takes them as pre-match features
(`PRE_MATCH_FEATURE_COLUMNS` in `prediction/component_dataset.py`), and the Issue #43
learned-rate candidate names them among its declared rate inputs (`CALENDAR_INPUT_COLUMNS`
in `prediction/learned_rate.py`). The two-stage model in `backtest/production.py` (feature
contract `two-stage-appearance-calendar-v1`, which no longer decides live squads) reads only
`fixture_count`: its expected-minutes stage scales by it and caps at that many full matches
(`prediction/minutes.py`), and `production_component_prediction` bounds its component split
by it (`prediction/production.py`). It attaches `home_fixture_count` too, and no stage of it
reads that column. The versioning requirement above is met by `fixture_snapshot_v1`, which
keys on the persistent team code and records the snapshot each row came from.

*The source's own difficulty rating is still unused, and now the reason is written down
rather than pending.* **No model reads `mean_fixture_difficulty` or
`minimum_fixture_difficulty`.** `attach_fixture_features` computes both on every call
(`aggregate_team_gameweek` in `src/squadopt/data/fixtures.py`), and since #152 it attaches
them only when every fixture row carries a capture instant. Every caller passes
`unproven_difficulty="omit"` (the ruling is under "Cross-owner coordination" below). No
archive row carries a capture instant, so on the development folds the two columns are
computed and then left off the frame. Every row of a live capture does carry one, so the live
scoring frame (`build_component_scoring_frame`, reached from `build_projection_handoff`)
has both columns attached, and the component models do not read them.
[`features/strength.py`](../src/squadopt/features/strength.py) explains why the rating was not
worth settling as a feature: it is opaque, so nobody here can say what it measures, and its
stability within a season is unverified. A strength estimate computed from results already
held is reproducible and its timing is ours to control, which is the better trade. Whether to
keep computing two columns nothing consumes (dropped on the development folds, attached and
unread on the live path) is an open question for both owners (three until 2026-09-25), since
`attach_fixture_features` is shared.

*The opponent-strength proposal: closed.* A fitted opponent rating applied at the decision
lost 0.91 realized points a fold ([`opponent_projection_note.md`](opponent_projection_note.md)),
and the frozen Route A candidate was closed as superseded on 2026-09-19 (#88), because the
two-stage rate it was declared against no longer decides live squads. A new attempt needs a
new declaration against the component base. What follows is the residual measurement that
first motivated it.

It was first measured not by wiring it in, but by asking
whether the operational control's out-of-sample residuals still move with it. They do:
attackers spread +0.162 across opponent-defence quartiles, monotone across all four;
goalkeepers and defenders spread +0.322 against opponent attacks, larger but not monotone.
The effect is bigger in the residuals than in the raw outcomes, so the existing feature set
is not spending it. See [`opponent_strength_signal.md`](opponent_strength_signal.md). That
is evidence for a candidate, not a candidate — consuming it changes the expected-points rate
and needs its own declaration and a single run under the frozen gates.

*`opponent_team_id` at player-gameweek grain: closed, by design.* It stays unmapped for the
reason item 10 gives: a player with two fixtures in one gameweek has two opponents, so the
column has no single correct value at that grain. Fixture context lives at fixture grain in
`fixture_snapshot_v1` instead.

### 5. Resolving the archive's price timing

**Now.** Prices are shifted back one gameweek because the archive does not document
whether `value` is the deadline price or one recorded afterwards, and the evidence is
suggestive rather than conclusive: in 2025-26 gameweek 1 it differs from `players_raw`
`now_cost` for 537 of 692 players, systematically higher.

Shifting is the conservative choice — a stale price costs accuracy, a leaky one costs
correctness — but it does cost up to one price change of precision on every row.

**The opening gameweek is the exception, and it is load-bearing.** GW1 has no earlier
price, so it keeps its own value and is the one gameweek in a season whose price timing
is unproven rather than hedged. Comparing GW1 against GW2 prices per player bounds the
exposure: 41/554 players changed price in 2021-22 (7.4%), 45/573 in 2022-23 (7.9%),
19/585 in 2023-24 (3.2%), 40/616 in 2024-25 (6.5%). Small in magnitude — at most one
0.1 step — but not random, because prices rise after good performances, so the affected
players are disproportionately the ones that scored, which is exactly the population a
squad optimizer selects.

This is harmless while walk-forward folds skip GW1, and it becomes load-bearing the
moment an opening gameweek is folded or backtested. It applies today to the
opening-decision backtest (`docs/opening_backtest.md`, #76), which reads the panel's
unshifted GW1 `price_tenths`; that measurement is a decision-level comparison rather
than a residual export and applies no availability rule, so the caveat qualifies it
rather than invalidating it. Proposed to the artifact's owner rather than edited into
the generated document. See `gw1_blocker_report_2021-2026.md` §4.

**Proposal.** Settle the question rather than hedging it. The official API's
`element-summary` endpoint records per-gameweek `value` for the current season, so once
2026-27 has a few gameweeks played, comparing its live values against the archive's
recorded ones for the same gameweeks answers it directly. If `value` turns out to be
the deadline price, `shift_price=False` becomes the correct default and the accuracy
comes back.

### 6. Additional source columns and older seasons

**When this was written**, only columns present in every supported season were mapped,
so expected goals, expected assists and `starts` were unused even where the archive had
them.

**Now.** The canonical panel (`vaastav.build_panel`) carries `starts` as a season-optional
column for 2023-24, 2024-25 and 2025-26 (`SEASON_OPTIONAL_COLUMNS`). 2022-23 has the column
but it reads zero for its first fifteen gameweeks, and because cleaning refuses a missing
value (item 2) that whole season goes without it. Expected goals and expected assists are
still not on the canonical panel: the football model reads them through its own archive
reader (`src/squadopt/data/sources/football_history.py`, 2022-23 to 2025-26, with its
own checks). Seasons before 2020-21 are still excluded because their gameweek files omit
`position` and `team`.

**Proposal.** Either handle per-season column availability explicitly — a panel with a
column missing for one season currently fails canonical validation — or restrict the
range when a richer feature set is needed. Older seasons could be recovered by joining
`position` and `team` from `players_raw.csv`, which is the same join the adapter already
performs for player identity.

### 7. Vectorized coercion

**Now.** Cleaning converts values one at a time so a failure can name the offending
record. That is the right trade at Sprint 0 sizes and the wrong one at full
historical scale.

**Proposal.** Vectorize the fast path and fall back to per-value conversion only to
build the error message. Behaviour must not change, so the existing cleaning and
validation tests are the specification and should pass untouched.

**Status: measured, and not worth doing.** This item reasons from "full historical
scale" without knowing what that scale would be. It is now known, so the deferral can be
closed on a number instead of staying open on an assumption.

`clean_canonical_dataset` on the real archive — 2020-21 through 2025-26, the six seasons
every measurement loads — costs **1.087 s** for **156,075 rows** across the nine canonical
columns the archive adapter produces, or 0.007 s per thousand rows, scaling linearly across
the six seasons. That is **26.6 %** of a `build_panel` call, which sounds material until you
ask how often the call happens.

**Once per run, or once per process.** Every caller loads the panel at the top and then
iterates folds over the frame in memory: the `measure_*` and `export_*` scripts,
`recommend_current_squad`, the four `experiments/` studies, and `fpl_capture`'s identity
check. `build_projection_handoff` builds it twice, once for the carried rates and the opening
fallback, and once more in `_component_table` for the component model's four training
seasons. Two callers build it in a process pool's initializer, once per worker process:

- the member-publication workers (`platform/publication_workers.py`), beside the parent's
  own build (`application/league_publication.py`). A league stage run with N workers above
  one cleans the archive at most N + 1 times, the workers in parallel (the spawned pool
  starts a worker only while members are waiting, so a league with fewer members than
  workers starts fewer). With one worker there is no pool, and the parent cleans it once.
- the season workers of `scripts/run_chip_bayesopt.py` (`_init_worker`, four by default),
  which clean it at most once each and nowhere else; with one worker the script runs the
  same initializer in its own process, once.

That is still about a second of cleaning per build, against a league stage the runbook
measured at about thirty-six minutes for fifteen members with eight workers (GW4 rehearsal,
[`weekly_runbook.md`](weekly_runbook.md)) and plans in hours once the Top-100 menu is on, so
the answer below does not change. The other entry point, `build_canonical_dataset`, is
reached only by the tests (`tests/integration/test_end_to_end.py`), over the committed
synthetic sample.

So a perfect vectorization has a **ceiling of about one second per panel build**, against
walk-forward benchmarks measured in hours. Against that, the change would edit the one module
whose own docstring exists to justify being the single place types change ("so a coercion
bug has exactly one home"), and would trade an actionable per-record message for a
column-wide one on the path that reports bad source data. Paying real risk in the coercion
layer to save a second once is the wrong trade in the opposite direction from the one this
item worried about.

**What would change the answer**, so this does not need re-measuring from scratch: cleaning
moving onto a per-fold or per-request path rather than a once-per-run one, or a source
arriving with an order of magnitude more rows *and* substantially more canonical columns
than the archive's nine. Either makes the ceiling worth having; neither is true today.

### 8. A versioned feature-generation contract

**When this was written**, `FeatureConfig` was explicit, frozen and validated, but it
carried no version identifier.

The experiment contract names "a versioned feature-generation contract and
time-aware historical data pipeline" as the activation dependency for its
`form_window` factor. The pipeline half was done then; the versioning half is now done
too (status below).

**Proposal.** A version on `FeatureConfig`, surfaced in whatever record an
evaluation run writes, so a stored result can be tied to the exact feature
definitions that produced it. Without it, two runs with different feature code but
identical parameters are indistinguishable after the fact, which defeats the
reproducibility the contract is asking for.

**Status: resolved.** `FEATURE_GENERATION_CONTRACT_VERSION` (`form_window_v1`) lives in
`src/squadopt/prediction/factors.py` beside the mapping it names, and every run that
writes a record surfaces it — the screening runner, the baseline benchmark, the learned
benchmark (which composes it with the Ridge feature contract), the control residual
manifest, and the multi-gameweek rehearsal.

The version sits on the module rather than on `FeatureConfig` itself, which is the
narrower placement and the right one: `FeatureConfig` is a parameter object that a caller
may construct with any windows, while the contract version names the *mapping* from a
declared factor to those windows. Versioning the parameter object would let a caller
claim a contract it did not follow.

Candidates that read beyond the frozen mapping declare their own contract on top of it
rather than editing this one — `two-stage-appearance-calendar-v1` for the production
projection and `learned-rate-calendar-appearance-v1` for the Issue #43 candidate — which
is what item 9 below requires of any wider feature bank.

## Cross-owner coordination

These are not data-layer decisions. Each needs agreement before implementation.

### Is the archive's `fixture_difficulty` a pre-match value? (**resolved: no**, 2026-08-19)

`features/fixtures.py` attaches `mean_fixture_difficulty` and
`minimum_fixture_difficulty` unshifted, on the ground that the fixture list and its
difficulty are published before the deadline. True of the live platform; not
established for the archive, which stores one value per club per venue per season
with no capture timestamp.

Measured while running `opponent_projection_study`: the value is constant within a
season in all four development seasons, so it cannot carry fixture-level hindsight.
But a rating written before a season should track the *previous* season's table more
closely than the coming one's, and 2024-25 does the reverse — **+0.940 against its own
season, +0.372 against the one before**. 2023-24 is marginal (+0.894 / +0.845);
2022-23 behaves correctly (+0.731 / +0.850).

The fixture *count* is unaffected, and the count is where the measured +58 points a
season lives. What needs a decision is whether the difficulty column is admissible on
development seasons, and what that invalidates. The full argument, and the two other
decisions it sits beside, are in
[the opponent rating handoff](opponent_rating_handoff.md).

**Settled since, for the strength columns.** A live capture taken 2026-08-16, five days
before the season's first kickoff, leaves `strength_attack_*` and `strength_defence_*` at
zero for all twenty clubs and fills only a coarse one-to-five `strength_overall_*`. A
finished season's archive carries the same fields populated on a thousand-point scale. The
archive's team-strength columns are not pre-season values.

**Being measured, for the difficulty column.** Difficulty *is* published before a season, so
it may legitimately be a pre-match feature; whether the archived copy equals the pre-season
one is now a live measurement rather than an argument.
[The pre-registration](preseason_difficulty_prereg.md) fixes the comparison and the
thresholds, and [the record](preseason_fixture_difficulty.md) pins the pre-kickoff capture
with its checksums.

**Ruled, on structure rather than correlation.** The column is **not admissible** as a
pre-match feature on development seasons. The correlation argument above is circumstantial;
this is not:

- The archived difficulty integer sits in the same CSV row as that fixture's final score,
  with `finished=True` and a populated `stats` blob. There is one `fixtures.csv` per season
  and no version history, so the row was written after the match was played — verified
  380/380 rows across three seasons.
- `2024-25/teams.csv` and `2025-26/teams.csv` carry that season's **final league table** in
  `position`, 20/20 clubs, cross-checked against the table recomputed from the same file's
  own scores. `players_raw.csv`'s latest `news_added` lands within days of each season's
  final kickoff, in all six completed seasons.
- The 2024-25 values track the outcome rather than the expectation: Nott'm Forest 4 at both
  venues (finished 7th), Man Utd 3 home / 2 away (15th), Leicester and Southampton 1/1 at
  `strength=975` — below the 1000 baseline every other season's promoted club sits at
  (finished 18th and 20th).
- Decisively: **the semantics are not uniform across seasons.** 2022-23 behaves like a
  pre-season rating (Newcastle 3/4 despite finishing 4th); 2024-25 does not. Choosing which
  seasons to trust would require exactly the hindsight the rule exists to avoid, so the
  column is inadmissible on all of them rather than on some.

**What it invalidates: nothing operational.** No prediction module mentions the column —
the deterministic control, the Ridge reference and the learned-rate candidate all exclude
it, and `rate_input_columns` names only the per-90, appearance and minutes-per-appearance
features plus `fixture_count` and `home_fixture_count`. Its only consumers are three
measurement studies, which read the **raw** `fixture_difficulty` rather than the aggregated
feature. So no recorded gate result, promotion decision or live decision depends on it. The
one result made unusable is the +1.74 realized points per gameweek from the published
rating — already flagged as the number most likely to be contamination. The fixture
**count** is unaffected, and that is where the measured +58 a season lives.

**Enforced, not just documented.** `attach_fixture_features` now refuses to attach the two
aggregated difficulty columns from fixture rows with no `captured_at_utc`, and offers no
option that attaches them anyway; the three callers that never read them state
`unproven_difficulty="omit"` explicitly. `data_contract.md` records why the per-column
classification could not express this.

### 9. Aligning `form_window` with the feature configuration (resolved)

The experiment contract defines `form_window` as a single scalar: "the number of
completed historical matches used to construct form-related features at a decision
timestamp".

`FeatureConfig` is shaped differently on purpose — `minutes_windows` and
`points_windows` are tuples, and `per_90_window` is separate — because several
windows are genuinely useful at once for model development.

Sprint 1 settled this as feature contract `form_window_v1`. A trial value `w` maps to
`minutes_windows=(w,)`, `points_windows=(w,)`, `per_90_window=w`,
`minutes_window=w`, and projection `per_90_window=w`. `min_periods=1` stays fixed.
`FormWindowMapping` implements the mapping and the baseline benchmark records its
contract version. Wider multi-window feature banks remain possible for later fitted
models, but they must use a different versioned factor contract rather than silently
changing this one.

### 10. Fixture-level grain

**Now.** Double gameweeks are handled: the archive adapter sums minutes and points
across a player's fixtures within a gameweek, and takes price once. What is *not*
handled is fixture-level context. `opponent_team` and `was_home` are deliberately
unmapped, because a player with two fixtures in one gameweek has two opponents and
possibly both a home and an away match, so at player-gameweek grain neither column has
a single correct value.

That is why fixture and opponent-strength features are absent, and it is a hard
blocker for them rather than an oversight.

**Proposal.** Fixture-level records beneath the player-gameweek grain, with the
player-gameweek view derived from them.

This changes the canonical contract that the optimization and software owners depend
on, so it needs agreement across all three owners rather than a unilateral edit. It is
the largest single item on this list.

**Status: resolved.** `fixture_snapshot_v1` is agreed across all three owners and
implemented: one row per team per fixture, keyed on
`(snapshot_id, season, fixture_id, team_id)`, with the player-gameweek view derived by
controlled aggregation. Six seasons are backfilled from the archive and the live path
writes into the same table. See the fixture section of
[data_pipeline.md](data_pipeline.md).

The two questions that had blocked the freeze are recorded below with the measurements
that settled them, because the reasoning matters more than the outcome if either is ever
revisited.

### 10a. Team identity across seasons

Measured against the pinned archive, and the result mirrors the player-identity finding
almost exactly.

| Consecutive seasons | Shared clubs | Kept `code` | Kept `id` |
| --- | ---: | ---: | ---: |
| 2020-21 → 2021-22 | 17 | 17 | 12 |
| 2021-22 → 2022-23 | 17 | 17 | 7 |
| 2022-23 → 2023-24 | 17 | 17 | 12 |
| 2023-24 → 2024-25 | 17 | 17 | 12 |
| 2024-25 → 2025-26 | 17 | 17 | 10 |

`code` survives every season boundary, 85 of 85. The integer `id` survives 53 of 85,
because it is assigned alphabetically within each season and shifts whenever a promoted
club sorts ahead of an existing one. The clearest case: `id` 14 is Newcastle in 2020-21
and 2021-22, then Man Utd from 2022-23 onward. The same number is a different club.

This matters because three identifier spaces are currently in play. The canonical panel
names a club by display name; the archive's `opponent_team` column is a per-season
integer; the live payload also uses a per-season integer. All six seasons reconcile
through `teams.csv` — the gameweek file's team names match its `name` column exactly, and
every `opponent_team` value falls inside its `id` column — so the bridge exists and is
verified. The live adapter already resolves its integer through the payload it came from,
which keeps the captured snapshot joinable without redefining anything.

**Resolved.** The fixture table keys on the persistent team `code`. It is the only one
of the three identifiers that means the same thing in two different seasons, and the
argument is identical to the one already accepted for players.

Confirmed across the source boundary as well: for the 17 clubs present in both the
2025-26 archive and the 2026-27 live payload, the code agrees 17 of 17, so the table
joins archive rows to live rows without a per-season translation.

The canonical panel still names a club by display name and was deliberately left alone —
that is a separate change to an existing canonical column, and the scenario generator
groups team-level shocks on it. `teams.csv` bridges the two, and all six seasons
reconcile through it. Converting the panel remains open and is now the only part of this
item still outstanding.

### 10b. Provenance for archive-backfilled fixture rows

`fixture_snapshot_v1` assumes a live capture. Four of its fields have no archive
equivalent, and this is now verified rather than assumed: the archive's `fixtures.csv`
carries `code`, `event`, `id`, `team_h`, `team_a`, both difficulty columns,
`kickoff_time`, `finished`, `finished_provisional`, `started`, `minutes`, `stats` and
`pulse_id` — and no deadline and no capture time.

| Field | Archive equivalent | Proposal |
| --- | --- | --- |
| `snapshot_id` | none | A reserved identifier naming the pin, e.g. `vaastav@8c97b2a` |
| `captured_at_utc` | none | Nullable for backfilled rows; fabricating a capture time would forge the one field leakage arguments rest on |
| `deadline_timestamp_utc` | none — deadlines live in the platform's event list, which the archive does not ship | Nullable for backfilled rows |
| `status` | `finished`, `finished_provisional`, `started` | Derived, and `final` for completed seasons |

**Resolved** as proposed: the archive's `snapshot_id` names the pin, `captured_at_utc`
and `deadline_timestamp_utc` are nullable for backfilled rows, and `status` is derived.
One consequence deserves stating rather than discovering later: postponement history is
unrecoverable. The archive files a rescheduled fixture under the gameweek it was
eventually played in, so no "this fixture was postponed" signal can be learned from
history. Live capture can observe it; a model cannot be trained on it.

The archive and live fixture payloads carry the same columns, so one adapter shape reads
both. The identifier spaces and the missing provenance fields are the only real
differences.

### 12. Import-order inconsistency in tests

**Now.** `tests/unit/` is not a package, so ruff's isort resolver treats `tests.*`
imports as third-party there while treating them as first-party in
`tests/conftest.py`. The grouping therefore differs between test files. Everything
passes lint; this is purely cosmetic.

**Proposal.** Either add `tests/unit/__init__.py`, or a `known-first-party` entry
under `[tool.ruff.lint.isort]` in `pyproject.toml`.

Both options touch shared test packaging or shared tool configuration, and adding
`tests/unit/__init__.py` also changes how pytest imports the existing optimizer
tests in that directory, so this was left for the software owner.
