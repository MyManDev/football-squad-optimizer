# Data Layer Follow-up Work

Known gaps in the Sprint 0 data layer, with the reasoning behind each deferral.
Everything here was left out deliberately, not overlooked. Sprint 0's goal was a
working, tested, deterministic skeleton; these items make it *better*, not
*working*.

Items are grouped by who has to decide. The first group is filed as issues, the
second is data-layer work, and the third needs agreement with the optimization or
software owner before anyone starts.

## Tracked as GitHub issues

Two items are filed rather than described here, because they are the immediate
Sprint 1 work and one blocks the other:

- **A walk-forward backtest split.** The requirement is already specified in
  [the experiment parameter contract](experimentation_spec.md) under "Time-based
  evaluation and leakage control"; the issue is about implementing a helper that
  satisfies it, not re-deciding it.
- **A price-based prior for a player's opening gameweek.** The baseline currently
  fills the one row with no history using a uniform per-position constant, so
  gameweek 1 projections cannot rank players. Price is fixed at the deadline, so
  using it is leakage-safe under this project's own timing rule. Blocked by the
  split above: any coefficient chosen without backtesting is invented precision.

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
see item 4.

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

### 3. Cross-season history

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

### 4. Columns with unverified timing

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

### 5. Fixture context features

**Now.** `opponent_team_id`, `is_home`, and `fixture_difficulty` are classified as
pre-match and carried through when present, but no feature uses them and the
synthetic sample does not contain them.

**Proposal.** Opponent strength and home advantage adjustments, once a verified
source supplies them. `fixture_difficulty` is only usable if the source's rating is
genuinely pre-match rather than computed afterwards. Nothing here may be fabricated
to make the feature set look richer.

The experiment contract adds a requirement beyond mere availability: fixture
information must be versioned as it was known at each decision timestamp. A single
current-value fixture table is not sufficient for backtesting.

### 6. A real source adapter

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

### 7. Vectorized coercion

**Now.** Cleaning converts values one at a time so a failure can name the offending
record. That is the right trade at Sprint 0 sizes and the wrong one at full
historical scale.

**Proposal.** Vectorize the fast path and fall back to per-value conversion only to
build the error message. Behaviour must not change, so the existing cleaning and
validation tests are the specification and should pass untouched.

### 8. A versioned feature-generation contract

**Now.** `FeatureConfig` is explicit, frozen, and validated, but it carries no
version identifier.

The experiment contract names "a versioned feature-generation contract and
time-aware historical data pipeline" as the activation dependency for its
`form_window` factor. The pipeline half is done; the versioning half is not.

**Proposal.** A version on `FeatureConfig`, surfaced in whatever record an
evaluation run writes, so a stored result can be tied to the exact feature
definitions that produced it. Without it, two runs with different feature code but
identical parameters are indistinguishable after the fact, which defeats the
reproducibility the contract is asking for.

## Cross-owner coordination

These are not data-layer decisions. Each needs agreement before implementation.

### 9. Aligning `form_window` with the feature configuration

The experiment contract defines `form_window` as a single scalar: "the number of
completed historical matches used to construct form-related features at a decision
timestamp".

`FeatureConfig` is shaped differently on purpose — `minutes_windows` and
`points_windows` are tuples, and `per_90_window` is separate — because several
windows are genuinely useful at once for model development.

For Design of Experiments to tune `form_window`, an agreed mapping between the one
factor and the several parameters is needed. Options include treating `form_window`
as the single window used by the projection while leaving the wider set for model
development, or collapsing the configuration to one window for experiment runs.
This should be settled with the optimization owner, who owns the factor definition.

### 10. Doubled and blank gameweeks

**Now.** The canonical key `(season, gameweek, player_id)` rejects duplicates, so a
player appearing twice in one gameweek cannot be represented at all. A blank
gameweek is simply an absent row, which works but is implicit.

**Proposal.** Fixture-level records beneath the player-gameweek grain, with the
player-gameweek view derived from them.

This is a schema change affecting the canonical contract that the optimization and
software owners depend on, so it needs agreement across all three owners rather
than a unilateral edit.

### 11. A shared contracts module

**Now.** `squadopt.data.schema` imports `Position`, `POSITIONS`, and
`PROJECTION_REQUIRED_COLUMNS` from the optimization package.

This was chosen on purpose: importing rather than restating means the two layers
cannot drift apart, and a test locks the expected projection column tuple so an
upstream change fails loudly. The cost is that the dependency points upward — the
data layer sits below optimization and should not read from it.

**Proposal.** A neutral module, for example `squadopt/contracts.py`, holding the
shared vocabulary, with both `data` and `optimization` importing from it. Every
data-layer reference already points at a single module, so the move itself is
mechanical once the location is agreed.

### 12. Type inference in `optimize_squad_from_csv`

**Now.** The integration adapter reads its CSV with `pd.read_csv(path)`, relying on
default type inference. Its docstring correctly states that it does not normalize
anything, and that `price_tenths` must already contain whole tenths.

The residual hazard is that inference fails *quietly* in two specific ways. A single
blank `price_tenths` cell promotes the column to `float64`, and because the optimizer
checks that column element-wise against `numbers.Integral`, the entire table is then
rejected with no indication that one empty cell caused it. Separately, an identifier
written `007` is silently read as `7`, which can collide with a genuinely different
player.

**Proposal.** Either route the adapter through `squadopt.data.load_csv`, which reads
as text and coerces explicitly with actionable errors, or read the contract columns
with explicit dtypes. This is the integration module's owner's call, not ours; it is
recorded here because the failure mode belongs to the data contract.

### 13. Import-order inconsistency in tests

**Now.** `tests/unit/` is not a package, so ruff's isort resolver treats `tests.*`
imports as third-party there while treating them as first-party in
`tests/conftest.py`. The grouping therefore differs between test files. Everything
passes lint; this is purely cosmetic.

**Proposal.** Either add `tests/unit/__init__.py`, or a `known-first-party` entry
under `[tool.ruff.lint.isort]` in `pyproject.toml`.

Both options touch shared test packaging or shared tool configuration, and adding
`tests/unit/__init__.py` also changes how pytest imports the existing optimizer
tests in that directory, so this was left for the software owner.
