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
| `prediction/config.py` | `BaselineProjectionConfig`: windows, opening fallback | **implemented** |
| `prediction/baseline.py` | Deterministic `expected_points` | **implemented** |
| `prediction/projection.py` | `build_projection_table(season=…, gameweek=t)` | **implemented** |

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
opening gameweek of a player's season has no history at all, and that single gap is
filled by an explicit per-position fallback in the prediction layer.

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

Three cases, in precedence order:

| Situation | Result | Why |
| --- | --- | --- |
| No history at all (opening gameweek) | Declared per-position fallback | Genuinely no signal; an explicit constant beats a silent zero |
| History exists, no minutes in the window | `0.0` | Not a gap — the player demonstrably did not feature |
| Otherwise | Formula, clamped at `0.0` | Realized points may be negative; a projection may not be |

The default fallback is deliberately **uniform** across positions. A differentiated
prior would imply a fitted claim this project has not earned; the per-position shape
exists so a later sprint can refine it without touching any call site. The
consequence is honest and tested: gameweek 1 projections are uniform, so the
optimizer returns a legal but undiscriminating squad. The skeleton never breaks —
it simply cannot rank players before any history exists.

`build_projection_table` copies `player_id`, `name`, `team_id`, `position`, and
`price_tenths` from the target gameweek's own row, because all five are fixed at
that gameweek's deadline. It then rechecks the contract itself — unique ids,
integral prices, finite non-negative points — so a violation names the projection
stage rather than surfacing as a puzzling rejection one module later.

## Two outputs, deliberately distinct

| | Prediction-ready historical dataset | Optimizer-ready projection table |
| --- | --- | --- |
| Rows | All players, all gameweeks | All candidate players, one target gameweek |
| Contains | Canonical columns, rolling features, `target_next_gw_points` | Exactly the six contract columns, plus optional diagnostics |
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
