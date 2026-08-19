# Projection Horizon Contract

## Purpose

The deterministic transfer planner consumes a validated `PlanningHorizon`, but the
production prediction pipeline projects one `DecisionPoint` at a time. Real multi-gameweek
planning needs a prediction-side handoff that projects several target gameweeks from one
captured snapshot. This contract fixes, from the planner's (consumer) side, what that
handoff must carry. The builder that produces it is owned by the data/prediction side.

Contract version: `projection_horizon_v1` (`squadopt.planning.horizon`).

## Builder interface

```python
class ProjectionHorizonBuilder(Protocol):
    def __call__(
        self,
        decision_snapshot: object,
        target_gameweeks: tuple[int, ...],
    ) -> ProjectionHorizon: ...
```

One call projects every requested target gameweek from a single captured decision
snapshot. The implementation must be leakage-safe with respect to the snapshot's capture
time and deterministic for identical inputs.

## Table

One row per `(gameweek, player_id)`, fixed columns:

```text
gameweek
player_id
name
team_id
position
price_tenths
expected_points
fixture_count
home_fixture_count
```

Rules:

- gameweeks are consecutive; **a blank gameweek is a row with `fixture_count = 0`, not a
  missing gameweek**;
- a blank row must project exactly zero expected points — a player cannot score in a
  gameweek with no fixture;
- a double gameweek is `fixture_count >= 2`; `home_fixture_count` may not exceed
  `fixture_count`;
- every projected gameweek carries the same player universe (transfers reason over one
  fixed pool per horizon);
- expected points are finite and non-negative; prices are non-negative integer tenths;
- positions come from the canonical `GK/DEF/MID/FWD` set;
- player and team IDs each use one consistent representation.

## Provenance

Required non-empty fields on the horizon object itself:

```text
season
source_snapshot_id
model_name
model_version
feature_contract_version
post_processing_contract_version
```

All rows must come from the same captured snapshot: mixing snapshots would blend two
information states into one decision. The `horizon_fingerprint` (SHA-256) covers the
canonical rows **and** the provenance fields, so two identical tables produced by
different models are different evidence.

## Conversion to the planner

```python
to_planning_horizon(horizon: ProjectionHorizon) -> PlanningHorizon
```

Buy and sell prices are both set to the projected `price_tenths`. No price transitions
are modeled; inventing them in the conversion would smuggle an unversioned price model
into the planner. A future price-transition contract replaces this conversion rather
than widening it.

## What this contract does not claim

- It does not implement the builder; that is the prediction side's deliverable, and the
  contract is exercised by synthetic horizons in `tests/unit/test_projection_horizon.py`
  until the real builder exists.
- It does not model price changes, injuries, or postponements over the horizon.
- It does not carry uncertainty; scenario-aware multi-week planning is a later stage and
  will extend, not reinterpret, this handoff.
