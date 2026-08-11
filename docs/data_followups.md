# Data Layer Follow-up Work

Known gaps in the Sprint 0 data layer, with the reasoning behind each deferral.
Everything here was left out deliberately, not overlooked. Ordered roughly by
value per unit of effort.

Sprint 0's goal was a working, tested, deterministic skeleton. These items make it
*better*, not *working*.

## 1. A real prior for a player's opening gameweek

**Now.** `BaselineProjectionConfig.opening_expected_points` fills the one row with
no history — a player's first gameweek of a season — with a declared constant. The
default is uniform across positions, so gameweek 1 projections cannot rank players
and the optimizer returns a legal but undiscriminating squad. This is asserted by
`test_the_opening_gameweek_is_solvable_but_uninformative`.

**Why it is uniform.** Differentiating positions with plausible-looking numbers
would imply a fitted claim this project has not earned. The per-position shape
exists so it can be refined without touching any call site.

**Proposal.** Use **price as a weak prior** for the opening gameweek. Price is
fixed at the deadline, so it is leakage-safe by the project's own timing rule, it
is already present in the canonical row, and it encodes the market's expectation of
a player — exactly the signal a rolling window cannot yet provide.

```text
expected_points(opening) = opening_price_coefficient * price_tenths / 10
```

**Why not in Sprint 0.** It needs a coefficient, and any value chosen without
backtesting is invented precision. The coefficient is a natural Design of
Experiments factor once a walk-forward evaluation exists (see item 2), so fitting
it belongs after that, not before.

**Also worth considering.** A previous-season carry-over prior, decayed, for
players with history in an earlier season. That interacts with item 5.

## 2. Walk-forward backtest split

**Now.** The feature dataset carries everything a backtest needs — shifted features
as `X`, same-row `total_points` as `y` — but no split utility exists.

**Proposal.** A time-ordered split helper that, for a target gameweek `t`, yields
training rows strictly before `t`. Random splits must stay impossible to express.

**Why it matters most.** Design of Experiments and Bayesian Optimization should
tune a trustworthy evaluation system. Without this, every later tuning result is
unverifiable.

## 3. Expected minutes as its own model

**Now.** Expected minutes is a shifted rolling mean of past minutes. A player
returning from injury or newly promoted into the starting eleven is projected from
a history that no longer describes them.

**Proposal.** A start-probability signal, ideally from `starts` when a source
provides it, combined with a minutes-given-start estimate. `availability_status`
would help, but only after its snapshot timing is verified — see item 6.

## 4. Partial optional columns

**Now.** An optional column that is present must be complete; a column with any
missing value is rejected. This avoids nullable dtypes and `pd.NA`, which silently
promote integer columns to float and get the whole projection table refused by the
optimizer.

**Proposal.** A per-column missing-value policy in configuration, so a source with
patchy `expected_goals` coverage can be used without weakening the guarantees on
required columns. Real historical data will force this.

## 5. Cross-season history

**Now.** `PLAYER_GROUP_COLUMNS` includes `season`, so every rolling window resets
at a season boundary. This is correct and tested — it is what stops one season's
final gameweeks leaking into the next season's opener — but it is also strict:
genuine information about a player is discarded every August.

**Proposal.** An explicitly decayed cross-season carry-over, computed only from
completed prior seasons, as a separate feature rather than a change to the group
key. The group key should stay strict; the carry-over should be opt-in and
separately tested for leakage.

## 6. Columns with unverified timing

**Now.** `selected_by_percent` and `availability_status` sit in
`AMBIGUOUS_TIMING_COLUMNS` and are excluded from features, because a historical
snapshot of either is often recorded after the fact.

**Proposal.** Inspect a real source, document when each value was actually
captured, and move them into `PRE_MATCH_COLUMNS` or `OUTCOME_COLUMNS` accordingly.
Until then, excluding them is the only defensible choice.

## 7. Fixture context features

**Now.** `opponent_team_id`, `is_home`, and `fixture_difficulty` are classified as
pre-match and carried through when present, but no feature uses them and the
synthetic sample does not contain them.

**Proposal.** Opponent strength and home advantage adjustments, once a verified
source supplies them. Nothing here may be fabricated to make the feature set look
richer.

## 8. A real source adapter

**Now.** The only adapter is `SAMPLE_ADAPTER`, which lives in test fixtures and
describes a fictional layout.

**Proposal.** A production adapter under `src/`, written against a real file whose
licensing and terms have been checked. Note the constraint recorded in
`docs/data_dictionary.md`: a source that reports post-gameweek prices must be
shifted at adapter level, because the canonical meaning of `price_tenths` is the
price payable at that gameweek's deadline.

## 9. Doubled and blank gameweeks

**Now.** The canonical key `(season, gameweek, player_id)` rejects duplicates, so a
player appearing twice in one gameweek cannot be represented. A blank gameweek is
simply an absent row.

**Proposal.** Fixture-level records beneath the player-gameweek grain, which is a
schema change and therefore needs coordination with the optimization and software
owners rather than a unilateral edit.

## 10. Vectorized coercion

**Now.** Cleaning converts values one at a time so a failure can name the offending
record. That is the right trade at Sprint 0 sizes and the wrong one at full
historical scale.

**Proposal.** Vectorize the fast path and fall back to per-value conversion only to
build the error message. Behaviour must not change, so the existing tests are the
specification.

## 11. A shared contracts module

**Now.** `squadopt.data.schema` imports `Position`, `POSITIONS`, and
`PROJECTION_REQUIRED_COLUMNS` from the optimization package. This guarantees the two
layers cannot drift, which is why it was chosen, but it points the dependency
upward: the data layer sits below optimization and should not read from it.

**Proposal.** A neutral module — `squadopt/contracts.py` or similar — owned by the
software architecture layer, holding the shared vocabulary. This is a **coordinated
change across three owners**, not a data-layer decision, which is why Sprint 0 left
it alone. Every data-layer reference already points at one module, so the move is
mechanical.

## 12. Import-order inconsistency in tests

**Now.** `tests/unit/` is not a package, so ruff's isort treats `tests.*` imports as
third-party there while treating them as first-party in `tests/conftest.py`. The
grouping therefore differs between test files. Everything passes lint; it is purely
cosmetic.

**Proposal.** Either add `tests/unit/__init__.py` or a `known-first-party` entry in
`pyproject.toml`. Both touch shared test packaging or shared configuration, so this
was left for the software owner rather than changed unilaterally.
