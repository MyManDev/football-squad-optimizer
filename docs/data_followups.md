# Data Layer Follow-up Work

Known gaps in the Sprint 0 data layer, with the reasoning behind each deferral.
Everything here was left out deliberately, not overlooked. Sprint 0's goal was a
working, tested, deterministic skeleton; these items make it *better*, not
*working*.

## Tracked as GitHub issues

Two items are filed rather than documented here, because they are the immediate
Sprint 1 work and one blocks the other:

- **A price-based prior for a player's opening gameweek.** The baseline currently
  fills the one row with no history using a uniform per-position constant, so
  gameweek 1 projections cannot rank players. Price is fixed at the deadline, so
  using it is leakage-safe under this project's own timing rule.
- **A walk-forward backtest split.** The price prior needs a coefficient, and any
  value chosen without backtesting is invented precision — so this one comes first.

## Documented here

The items below are not yet real work items, so they are recorded rather than
filed. When one becomes actual work, open an issue for it and delete it from this
file, so there is only ever a single record of it.

## 1. Expected minutes as its own model

**Now.** Expected minutes is a shifted rolling mean of past minutes. That is fine
for a steady starter and wrong for the cases that matter most: a player returning
from injury, or one newly promoted into the starting eleven, is projected from a
history that no longer describes them.

Because the baseline is `points_per_90 * expected_minutes / 90`, an error here
propagates directly into every projection.

**Proposal.** A start-probability signal combined with a minutes-given-start
estimate. `starts` is the natural input when a source provides it.
`availability_status` would help, but only after its snapshot timing is verified —
see item 4.

## 2. Partial optional columns

**Now.** An optional column that is present must be complete; a column with any
missing value is rejected.

This is not pedantry. One missing value promotes an integer column to float, the
optimizer checks `price_tenths` element-wise against `numbers.Integral`, and the
whole projection table then gets refused far from the real cause. Nullable dtypes
and `pd.NA` fail the same way.

**Proposal.** A per-column missing-value policy in configuration, so a source with
patchy `expected_goals` coverage can be used without weakening the guarantees on
required columns. Real historical data will force this immediately.

## 3. Cross-season history

**Now.** `PLAYER_GROUP_COLUMNS` includes `season`, so every rolling window resets
at a season boundary. This is correct and tested — it is what stops one season's
final gameweeks leaking into the next season's opener — but it is also strict:
genuine information about a player is discarded every August.

**Proposal.** An explicitly decayed cross-season carry-over, computed only from
completed prior seasons, added as a **separate feature** rather than as a change to
the group key. The group key stays strict; the carry-over is opt-in and separately
tested for leakage, because it is the one feature that deliberately crosses the
boundary the rest of the layer defends.

This also offers a second option for the opening-gameweek prior, alongside the
price-based approach filed as an issue.

## 4. Columns with unverified timing

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

## 5. Fixture context features

**Now.** `opponent_team_id`, `is_home`, and `fixture_difficulty` are classified as
pre-match and carried through when present, but no feature uses them and the
synthetic sample does not contain them.

**Proposal.** Opponent strength and home advantage adjustments, once a verified
source supplies them. `fixture_difficulty` is only usable if the source's rating is
genuinely pre-match rather than computed afterwards. Nothing here may be fabricated
to make the feature set look richer.

## 6. A real source adapter

**Now.** The only adapter is `SAMPLE_ADAPTER`, which lives in test fixtures and
describes a fictional layout.

**Proposal.** A production adapter under `src/`, written against a real file whose
licensing and terms have been checked. Two constraints carry over from the contract:

1. `price_tenths` means the price payable at that gameweek's deadline. A source
   reporting post-gameweek prices must be shifted at adapter level and the
   deviation documented, or the projection silently uses a future price.
2. Platform-specific encodings, including numeric position codes, belong in the
   adapter's `position_codes`, never in the canonical schema.

Large third-party dumps must not be committed; `data/raw/` is git-ignored for this
reason.

## 7. Doubled and blank gameweeks

**Now.** The canonical key `(season, gameweek, player_id)` rejects duplicates, so a
player appearing twice in one gameweek cannot be represented at all. A blank
gameweek is simply an absent row, which works but is implicit.

**Proposal.** Fixture-level records beneath the player-gameweek grain, with the
player-gameweek view derived from them.

**Coordination required.** This is a schema change affecting the canonical contract
that the optimization and software owners depend on, so it needs agreement across
all three owners rather than a unilateral edit.

## 8. Vectorized coercion

**Now.** Cleaning converts values one at a time so a failure can name the offending
record. That is the right trade at Sprint 0 sizes and the wrong one at full
historical scale.

**Proposal.** Vectorize the fast path and fall back to per-value conversion only to
build the error message. Behaviour must not change, so the existing cleaning and
validation tests are the specification and should pass untouched.

## 9. A shared contracts module

**Now.** `squadopt.data.schema` imports `Position`, `POSITIONS`, and
`PROJECTION_REQUIRED_COLUMNS` from the optimization package.

This was chosen on purpose: importing rather than restating means the two layers
cannot drift apart, and a test locks the expected projection column tuple so an
upstream change fails loudly. The cost is that the dependency points upward — the
data layer sits below optimization and should not read from it.

**Proposal.** A neutral module, for example `squadopt/contracts.py`, holding the
shared vocabulary, with both `data` and `optimization` importing from it.

**Coordination required.** This touches the software architecture owner's area and
the optimization owner's module, so it is not a data-layer decision. Every
data-layer reference already points at a single module, so the move itself is
mechanical once the location is agreed.

## 10. Import-order inconsistency in tests

**Now.** `tests/unit/` is not a package, so ruff's isort resolver treats `tests.*`
imports as third-party there while treating them as first-party in
`tests/conftest.py`. The grouping therefore differs between test files. Everything
passes lint; this is purely cosmetic.

**Proposal.** Either add `tests/unit/__init__.py`, or a `known-first-party` entry
under `[tool.ruff.lint.isort]` in `pyproject.toml`.

**Why it was not simply fixed.** Both options touch shared test packaging or shared
tool configuration, and adding `tests/unit/__init__.py` also changes how pytest
imports the existing optimizer tests in that directory. Left for the software owner
rather than changed unilaterally.
