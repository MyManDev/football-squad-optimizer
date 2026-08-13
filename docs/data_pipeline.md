# Data Pipeline

How local raw player-gameweek records become an optimizer-ready projection table.
Schemas are defined in [the data contract](data_contract.md); per-column detail is
in [the data dictionary](data_dictionary.md).

## Stages

```text
local CSV / Parquet
  -> loaders     read only, no transformation
  -> adapters    explicit raw-name -> canonical-name mapping
  -> validation  reject structurally broken or contradictory records
  -> cleaning    normalize positions, prices, dtypes; deduplicate; sort
  -> canonical player-gameweek dataset          (season, gameweek, player_id)
  -> features    leakage-safe shifted rolling aggregations
  -> prediction  deterministic baseline expected_points
  -> optimizer-ready projection table           one target gameweek
```

Each stage consumes only the previous stage's declared output. The optimizer sees
none of it: not source names, not cleaning rules, not the loader.

## Modules

| Module | Responsibility | Status |
| --- | --- | --- |
| `data/schema.py` | Canonical columns, key, orderings, position vocabulary, price factor, time-of-knowledge classes | **implemented** |
| `data/errors.py` | `DataError` hierarchy, disjoint from optimization errors | **implemented** |
| `data/loaders.py` | Local CSV/Parquet reading, no transformation | **implemented** |
| `data/adapters.py` | Explicit raw-to-canonical column mapping | **implemented** |
| `data/validation.py` | Canonical dataset integrity checks with actionable errors | **implemented** |
| `data/cleaning.py` | Position/price/dtype coercion — the only place types change | **implemented** |
| `data/pipeline.py` | `build_canonical_dataset()` composing the above, and ordering | **implemented** |
| `features/config.py` | `FeatureConfig`: windows, `min_periods`, feature naming | **implemented** |
| `features/rolling.py` | The single shifted-rolling primitive | **implemented** |
| `features/builder.py` | `build_feature_dataset()` | **implemented** |
| `features/cross_season.py` | Carry-over from completed earlier seasons | **implemented** |
| `data/sources/vaastav.py` | The real historical archive: layout, identity, corrections | **implemented** |
| `prediction/config.py` | `BaselineProjectionConfig`: windows, fitted opening-price prior | **implemented** |
| `prediction/baseline.py` | Deterministic `expected_points` | **implemented** |
| `prediction/projection.py` | `build_projection_table(season=…, gameweek=t)` | **implemented** |
| `prediction/opening.py` | `build_opening_projection_table()` for a season with no played matches | **implemented** |
| `backtest/splits.py` | `DecisionPoint`, season ranking, the time-ordered split | **implemented** |
| `backtest/folds.py` | `build_walk_forward_folds()` producing `EvaluationFold` objects | **implemented** |

Design rules that keep the layer refactorable: all constants live in `schema.py`
and are imported, never restated; I/O is confined to `loaders.py` so every
transformation is a pure function testable without touching disk; configuration is
an explicit frozen dataclass rather than keyword arguments spread across call
sites.

## Leakage control

The rule is per-column, not per-row — see the contract's time-of-knowledge
section. Two mechanisms enforce it.

**Structural.** All shifting and windowing goes through one primitive in
`features/rolling.py`. It groups by `PLAYER_GROUP_COLUMNS` (`season`,
`player_id`), sorts by `PLAYER_TIME_SORT_COLUMNS`, and applies `shift(1)` before
`rolling(n)`. Because there is exactly one such code path, there is exactly one
place to audit. Aggregating an outcome column without a shift is refused via
`is_outcome_column()`.

Concretely:

```python
frame.groupby(list(PLAYER_GROUP_COLUMNS))[column].transform(
    lambda values: values.shift(1).rolling(window, min_periods=min_periods).mean()
)
```

The primitive verifies rather than re-sorts: the builder sorts once, and the
primitive then confirms each player's rows ascend in gameweek order. Only order
*within* a group matters — `groupby` collects a player's rows however they are
scattered, and `shift(1)` follows their relative order — so groups need not be
contiguous and the check asserts exactly that and nothing more.

Two related guards live in the same place. Asking to roll a **pre-match** column
is refused, because shifting a value already known at the deadline discards
information rather than protecting anything. Asking to roll an **unclassified**
column raises, so a newly added canonical column cannot quietly acquire a rolling
feature before someone decides when it is known.

Rate features are ratios of shifted **sums**, not means of per-row ratios: a
ten-minute cameo must not weigh as much as a full match, and a per-row ratio would
divide by zero for every gameweek a player did not feature. The rate is left
*undefined* rather than zero when no minutes were played in the window.

**Behavioural.** Five test families, because the structural argument is a claim
until it is measured:

1. *Future-mutation invariance* — mutating outcome values in rows `>= t` leaves
   every feature for rows `< t` bit-identical.
2. *Truncation equivalence* — features computed on data truncated at `t` equal
   those computed on the full dataset, for all rows `< t`. Stronger than mutation
   invariance: it catches whole-dataset operations that mutation testing misses.
3. *Season isolation* — a season's opening gameweeks are unaffected by the
   previous season's closing gameweeks.
4. *Row-order invariance* — shuffled input yields identical output.
5. *Exact expected values* — hand-computed rolling values are asserted literally,
   so the test does not merely re-derive the implementation.

Forbidden throughout: `bfill()` on rolling gaps, whole-dataset normalization
before a temporal split, season-wide aggregates as features, random train/test
splits, and any use of `target_next_gw_points` as an input.

Insufficient history yields `NaN` at the feature layer. `NaN` is never
back-filled; the prediction layer replaces it with an explicit configured fallback,
so "we do not know yet" and "the value is zero" stay distinguishable.

`min_periods` defaults to 1, so a player's second gameweek already carries one real
prior observation. Early values are noisier than a full window, but one real
observation beats none, and every gameweek after the first stays projectable —
which matters because a squad has to be picked for those gameweeks too. Only the
opening gameweek of a player's season has no history at all. Earlier-season carry-over
fills that gap where available; otherwise the fitted deadline-price prior ranks players.

## Determinism

Same input plus same config gives byte-identical output. Guaranteed by: a
deterministic sort before every time-dependent operation and on final output;
`groupby(sort=True)`; no randomness anywhere in the path; `Decimal` with
`ROUND_HALF_UP` for price conversion instead of binary float arithmetic; and no
reliance on input row order or on dictionary iteration order.

## Baseline projection

```text
expected_points = points_per_90_last_N * minutes_last_N / 90
```

Both inputs are shifted rolling features, so a gameweek `t` projection reads only
earlier gameweeks. Scaling a rate by expected playing time captures the dominant
driver of fantasy scoring — whether a player is on the pitch at all — which a plain
points average misses: it would rate a substitute who scored once in ten minutes
as highly as a regular starter.

Four cases, in precedence order:

| Situation | Result | Why |
| --- | --- | --- |
| Within-season history exists | Formula, clamped at `0.0` | Realized points may be negative; a projection may not be |
| History exists, no minutes in the window | `0.0` | Not a gap — the player demonstrably did not feature |
| No within-season history, earlier seasons carried | Same formula on the carry-over | The opening gameweek can rank players instead of treating everyone alike |
| No record anywhere | `opening_price_coefficient * price_tenths / 10` | Deadline price is a leakage-safe weak prior for a genuine debut |

The third case needs the feature dataset to carry the cross-season columns, which
`build_feature_dataset(..., cross_season=...)` attaches. It is off by default: it only
means anything for a panel spanning several seasons, and a caller working within one
season should not silently gain two always-missing columns.

Measured on six real seasons, the carry-over covers **57% to 67%** of opening-gameweek
players. The remainder — new signings from abroad, promoted-team players, and debutants —
uses the fitted price rule. The coefficient lives in `BaselineProjectionConfig`, not at a
call site. Setting it to `None` explicitly restores the uniform per-position fallback.

`build_projection_table` copies `player_id`, `name`, `team_id`, `position`, and
`price_tenths` from the target gameweek's own row, because all five are fixed at
that gameweek's deadline. It then rechecks the contract itself — unique ids,
integral prices, finite non-negative points — so a violation names the projection
stage rather than surfacing as a puzzling rejection one module later.

## Opening-price prior backtest

Contract `opening_price_prior_v1` fits a non-negative, zero-intercept least-squares rule:

```text
expected_points(opening) = coefficient * price_tenths / 10
```

The fit uses 2,826 opening-gameweek player rows from 2020-21 through 2024-25 in the
pinned vaastav archive. It yields `0.29940564635958394`. The 690 rows in 2025-26 GW1 are
an untouched holdout; changing their outcomes cannot change the coefficient, which is
covered by a synthetic leakage test.

| Holdout rule | MAE | RMSE | Mean error |
| --- | ---: | ---: | ---: |
| Price only | 1.729360 | 2.453682 | 0.120833 |
| Decayed carry-over + constant | 2.321033 | 2.815709 | 1.011354 |
| Decayed carry-over + price | 1.738257 | 2.405757 | 0.301912 |

Carry-over covers 390 of 690 holdout players (56.52%). The production precedence is
the hybrid rule: keep the player-specific carry-over when available, and use price only
for the 300 players without a usable earlier record. Reproduce the fit and report with:

```powershell
.venv\Scripts\python -m scripts.run_opening_prior_backtest
```

The archive does not formally document the timestamp of historical GW1 `value`. The
backtest therefore inherits the adapter's existing conservative GW1 treatment and records
the pinned source revision. For a genuinely upcoming season, `players_raw.now_cost` is
unambiguous because no match or price change has occurred yet.

## Walk-forward backtesting

`squadopt.backtest` sits above the data, feature, prediction, and evaluation layers
and owns the time axis. What counts as "before" a decision is decided in one module
and nowhere else, so no consumer re-derives it and no consumer can bypass it.

A `DecisionPoint` is a season and gameweek: the boundary between what is known and
what is not. Two views exist around it, deliberately separate:

| View | Contents | Used for |
| --- | --- | --- |
| `rows_before` | Strictly earlier rows | Fitting a model, which must never see the outcome it predicts |
| `rows_through` | Earlier rows **and** the decision gameweek | Building the projection |
| `realized_points_at` | Only the decision gameweek's `player_id` and `total_points` | Scoring, read only after the decision is frozen |

`rows_through` includes the decision gameweek on purpose rather than by oversight.
Building features for gameweek `t` needs row `t` for its pre-match columns — price,
club, and position are fixed at that deadline — while every rolling aggregation is
shifted, so the row's own outcome cannot reach its own features. Later gameweeks are
absent entirely, which makes "the future does not exist" structurally true rather
than merely tested.

Season order is ranked from sorted labels by default. That works for the
conventional `YYYY-YY` label, but it is a property of the naming convention rather
than a guarantee, so `season_order` lets a caller state the order instead of hoping
the default is right. A test proves the explicit order genuinely changes which rows
count as history.

`min_prior_gameweeks_in_season` defaults to 1, skipping each season's opener. A
season-scoped rolling feature has no history there, and opening decisions use a separate
carry-over and fitted-price-prior workflow. History is counted from rows that actually
exist, not from gameweek numbers: a panel starting at gameweek 5 has no history at
gameweek 5.

`seasons` restricts which seasons produce decisions while leaving earlier seasons
available as history. That is how a holdout season stays unscored without being
deleted from the panel.

**Random splits are not expressible.** No function accepts a seed, shuffle, fraction,
or `random_state`, and a test asserts the public surface never grows one.

The projection step is injected rather than hard-coded, so a later sprint can pass a
fitted model without touching the splitting logic — the part that must not be
re-derived. A test confirms the injected builder never receives rows after its
decision gameweek.

`build_walk_forward_folds` emits `EvaluationFold` objects in chronological order,
which matters because the evaluator measures squad turnover between adjacent folds;
a non-chronological sequence would report turnover between unrelated gameweeks.

Leakage is tested at fold level too, not just feature level: a fold built from the
full panel equals one built from a panel truncated after its decision gameweek, and
rewriting later outcomes cannot move a projection. The complementary assertion
matters as much — rewriting the decision gameweek's outcome *must* move the realized
points, or nothing is actually being scored.

## Two outputs, deliberately distinct

| | Prediction-ready historical dataset | Optimizer-ready projection table |
| --- | --- | --- |
| Rows | All players, all gameweeks | All candidate players, one target gameweek |
| Contains | Canonical columns and rolling features; same-row `total_points` is the label | Exactly the six contract columns, plus optional diagnostics |
| Purpose | Model development and walk-forward backtesting | Optimizer input |

Conflating them is how a training label reaches the optimizer, so they are built
by separate functions with separate tests.

## Testing

Unit tests are offline and use small synthetic fixtures; nothing in the core suite
requires network access or platform data. Fixtures are deliberately monotone and
asymmetric across gameweeks, because constant-valued synthetic data hides leakage:
a shifted and an unshifted feature look identical when every gameweek is the same.

`tests/integration/test_end_to_end.py` runs the real chain — local file, canonical
dataset, features, projections, CP-SAT — and asserts a solved squad, the configured
squad shape, positional quotas, the per-team limit, the budget, and a captain who
actually starts. The optimizer is a required project dependency, so it is exercised
directly rather than skipped; a Parquet engine is *not* a dependency, so only that
one loader test is conditional.

The projection contract test validates the table with the optimizer's own
`validate_players`, which is the strongest available check: it is the consumer's
real validator, not a restatement of it.

## Reading and adapting

`load_csv` reads every column as text on purpose. Type inference is a silent
transformation: it strips leading zeros from identifiers and promotes an integer
column to float as soon as one row is blank — which is exactly what makes the
optimizer reject a `price_tenths` column. Coercion therefore happens once, in
cleaning, where it can report the offending value. `load_parquet` keeps native
dtypes because the file records them explicitly, so cleaning accepts both forms.
Parquet needs an engine that is not a project dependency; a missing engine is
reported as a data-source error rather than a bare `ImportError`.

A `SourceAdapter` declares one source's layout: raw column names, encoded position
values, and whether prices arrive in tenths or whole units. It is validated at
construction, so an adapter that cannot produce the required schema, maps two raw
columns onto one canonical column, or declares a position code for a position that
does not exist is rejected immediately rather than failing confusingly mid-run.
`apply_adapter` renames, drops unmapped columns so a raw platform name cannot
travel downstream, and returns an independent copy. Optional canonical columns the
source lacks are simply absent — never created.

## Cleaning, validation, and stage boundaries

Three stages, three jobs, no overlap: cleaning decides types, validation judges
integrity, and the pipeline imposes order. Duplicates are *rejected*, never
silently dropped, so no stage deduplicates.

Coercion is lossless by construction, and the rule differs by column meaning. For
a **quantity**, a leading zero is formatting: `01` becomes gameweek `1`. For an
**identifier**, a leading zero is part of the identity, so `007` must not become
`7` and collide with a different player. Identifier columns therefore become
integers only when every value round-trips back to the same text; a single
non-reversible value keeps the whole column as text, because the contract requires
one consistent identifier type per column.

Missing values are rejected rather than imputed. This is not pedantry: one missing
value promotes an integer column to float, the optimizer checks `price_tenths`
element-wise against `numbers.Integral`, and the whole projection table would then
be refused far away from the real cause.

Price conversion uses `Decimal` with `ROUND_HALF_UP`, never binary floats. In
binary, `int(4.7 * 10)` is `46`, and a price one tenth off changes which squads are
affordable. Declaring `price_unit="tenths"` makes a fractional price an error
instead of something to round, since a fraction there means the declared unit is
wrong.

Values are converted one at a time rather than with vectorized casts. That is
slower, but a vectorized cast reports failure as an opaque column-wide error,
and at Sprint 0 sizes an actionable message naming the bad record is worth more.

`build_canonical_dataset(raw, adapter=..., season=..., max_gameweek=...)` accepts
a declared `season` for a single-season extract that does not carry the label.
Declaring a season that contradicts existing values is refused: relabelling would
silently merge two seasons into one rolling-window group, which is exactly the
leakage the season group key exists to prevent.

`max_gameweek` is optional because a competition's length is not a schema fact.
Nothing hard-codes 38.

## Data files

`data/sample/raw_player_gameweeks.csv` is small, entirely synthetic, and
regenerated by `python -m scripts.generate_sample_data`. A test asserts the
committed file still matches its generator, so the data is reproducible from code
instead of being an opaque blob. It is deliberately raw-shaped: fictional column
names, numeric position codes, decimal prices, non-canonical row order, and one
column that must be dropped.

Real third-party historical dumps live in git-ignored directories under `data/`
and are never committed: licensing is unverified and the repository is not a data
store.

## Real historical data

Six seasons, 2020-21 through 2025-26, from the
[vaastav archive](https://github.com/vaastav/Fantasy-Premier-League): 156,075
player-gameweek rows and 1,960 players, of whom 1,133 appear in more than one season.

The row count includes 101 rows restored by accepting `GKP` alongside `GK`. The archive
spells goalkeeper as `GKP` in 2021-22 gameweek 37 and as `GK` everywhere else, so the
original position filter silently dropped every goalkeeper in that gameweek — 80
players, all in one round, and no other season affected. The consequence was confined
to those goalkeepers' shifted rolling features in gameweek 38, which read one gameweek
less history than they should have. No benchmark needed re-running: the baseline
benchmark is measured on 2025-26, which contains no `GKP` rows, and every other real-data
run postdates the fix.

```bash
python -m scripts.fetch_historical_data      # download and verify
python -m scripts.recommend_opening_squad    # opening-gameweek squad from that data
```

The data is not committed — see [data/sources/README.md](../data/sources/README.md) for
the licensing reasoning and how a pinned commit plus checksums keeps every machine on
identical bytes.

Four source facts were established by inspecting the archive, and each one shaped the
adapter:

| Finding | Consequence |
| --- | --- |
| `code` is stable across seasons; `id` is not — 479 of 479 shared players keep `code`, 1 keeps `id` | Player identity is `code`, recovered by joining gameweek rows to `players_raw.csv` |
| 2016-17 and 2018-19 omit `position` and `team` | The supported range starts at 2020-21 |
| Duplicate rows arise from two unlike causes | Repeated fixture records are dropped; genuine double gameweeks are summed |
| `value` timing is undocumented and differs from `now_cost` for 537 of 692 players in 2025-26 | Prices are shifted back one gameweek by default |

The price shift deserves its reasoning stated plainly. If `value` is recorded after a
gameweek, using it directly would let that gameweek's own result reach its own
decision: a player who scored well rises in price, so the price would quietly encode
the outcome. A stale price costs accuracy; a leaky one costs correctness. The opening
gameweek keeps its own value, and that residual approximation sits in exactly the
gameweek walk-forward folds already exclude.

`xP` is never used as a feature. The archive documents it as scraped after the gameweek
and possibly carrying post-match information — a leakage trap wearing the name of a
prediction.

Manager entries — `AM` rows from 2024-25, twenty per season — are excluded, because a
manager is not a squad-eligible player under the canonical contract.

## Capturing a live season before a deadline

The archive publishes a gameweek after it has been played, so it cannot answer what the
roster looked like before a deadline. A live season needs its own capture.

```bash
python -m scripts.capture_deadline_snapshot --dry-run   # read and report, write nothing
python -m scripts.capture_deadline_snapshot             # capture
python -m scripts.capture_deadline_snapshot --list      # what is held locally
```

The source and the reasoning behind choosing it are in
[live_data_source_options.md](live_data_source_options.md). Three properties of the
capture matter more than the mechanics:

**Capture time is data, not metadata.** Prices move daily and availability hourly near
a deadline, so a capture taken three days early describes a squad nobody can still
enter. The instant is stamped once after both endpoint reads complete, so the pair
cannot straddle a deadline, and it must state a UTC offset — a naive timestamp is
rejected rather than assumed.

**The target gameweek is derived, not declared.** The payload publishes an `is_next`
flag and the resolver ignores it. That flag is state the source maintains on its own
schedule and we cannot establish when it was last updated; comparing a published
deadline against our own capture instant is something we can show. The deadline instant
itself counts as closed, because a squad decided at the moment of closing cannot be
entered.

**A snapshot is never rewritten.** Payloads are checksummed individually, the
provenance is fingerprinted, and the identifier is rebuilt from the metadata on every
read. The three checks fail differently on purpose: edited bytes, edited provenance, and
a snapshot moved into another's directory. Backdating a capture would make a leaky
decision look timely, so provenance is protected as carefully as content.

What the capture produces is a **player snapshot**, not a canonical panel row. A
canonical row requires `minutes` and `total_points`, and a roster read before kick-off
has neither, so it carries only the five deadline-known fields a projection is assembled
from. Availability is captured in the payload and deliberately absent from that table:
it is applied later as an explicit inference rule, and a column would invite it to
become a feature.

Captured identities are reconciled against the archive on every capture. A new player
is expected and reported; no overlap at all is rejected, because a roster of complete
unknowns means the two sides are keyed on different identifier spaces rather than that
the league has been replaced.

Verified against the live endpoints on 2026-08-13: 38 published gameweeks, the next open
deadline resolving to gameweek 1 at `2026-08-21T17:30:00Z`, 584 players across 20 teams,
and 501 of them already carrying history. The remaining 83 are cold starts, and that
count is a floor rather than a final figure — clubs register more players before the
opening deadline.

Snapshots stay in a git-ignored directory. The source permits private use and forbids
redistribution, and unlike the archive a capture cannot be re-fetched later anyway, so
committing a checksum would not let anyone reproduce it. The audit trail runs the other
way: a decision report names the snapshot it was made from and repeats its fingerprint,
and that report is what gets committed.

## Projecting a season that has not started

A season about to begin has no `merged_gw.csv` at all: its players arrive as a roster.
`build_opening_projection_table` joins the two halves — the roster supplies identity,
club, position, and the opening price, all fixed at the deadline; the carried record
supplies the expectation.

That roster price is unambiguous in a way no in-season price is: the season has not
begun, so nothing can have moved it.

The table carries a `has_prior_record` flag beyond the six contract columns, so a caller
can see how much of the pool rests on real history rather than on the price prior. For
2026-27 that is 384 of 567 players.
