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

### 4. Fixture context features

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

### 5. Resolving the archive's price timing

**Now.** Prices are shifted back one gameweek because the archive does not document
whether `value` is the deadline price or one recorded afterwards, and the evidence is
suggestive rather than conclusive: in 2025-26 gameweek 1 it differs from `players_raw`
`now_cost` for 537 of 692 players, systematically higher.

Shifting is the conservative choice — a stale price costs accuracy, a leaky one costs
correctness — but it does cost up to one price change of precision on every row.

**Proposal.** Settle the question rather than hedging it. The official API's
`element-summary` endpoint records per-gameweek `value` for the current season, so once
2026-27 has a few gameweeks played, comparing its live values against the archive's
recorded ones for the same gameweeks answers it directly. If `value` turns out to be
the deadline price, `shift_price=False` becomes the correct default and the accuracy
comes back.

### 6. Additional source columns and older seasons

**Now.** Only columns present in every supported season are mapped, so expected goals,
expected assists, and `starts` are unused even where the archive has them. Seasons
before 2020-21 are excluded entirely because their gameweek files omit `position` and
`team`.

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
