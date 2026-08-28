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
snapshot. At gameweek one, the base projection is built from completed history. Later in
the season, the first target must have a validated `projection_handoff_v1` produced for
that exact season, gameweek and snapshot. The same captured information state is then
held fixed across the requested calendar. The implementation must be leakage-safe with
respect to the snapshot's capture time and deterministic for identical inputs.

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

## Application operation

`squadopt.application.plan_horizon(HorizonPlanRequest(...))` is the transport-neutral
operation used by command-line, worker, and later HTTP adapters. It resolves the named
capture, validates the in-season handoff against that capture, reads the held squad from
the previous immutable ledger entry, builds the horizon, solves it, and writes one
fingerprinted artifact.

The operation returns `HorizonPlanResult`; callers do not scrape console text. An
`OPTIMAL` plan is marked `proven`. A `FEASIBLE` plan is refused by default and may be
recorded only when the caller explicitly enables shadow output, in which case it is
marked `shadow_unproven`. Replaying identical inputs reuses the same bytes and path;
different bytes may never overwrite an existing artifact.

`python -m scripts.plan_transfer_horizon` is only the CLI adapter over this operation.
It contains argument parsing and presentation, not planning or artifact business logic.

## Batch evidence

`squadopt.application.plan_horizon_batch(...)` runs the supported horizons against the
same season, snapshot, handoff, ledger origin, and solver-budget policy. Its immutable
`live_transfer_horizon_batch_v1` manifest links the fingerprinted child artifacts by
paths relative to the artifact root, so workstation directories never enter portable
evidence.

The one-week result is the only decision-eligible control. Three- and five-week results
are labelled `research_shadow` even when the solver proves their mathematical optimum:
solver proof is not evidence that a longer forecast is calibrated. A failed child leaves
already completed immutable artifacts available for replay but produces no batch
manifest, preventing a partial run from looking complete.

```powershell
.venv\Scripts\python -m scripts.run_transfer_horizon_batch `
  --horizons 1,3,5 `
  --in-season-projection data/handoffs/2026-27-gw02.json
```

## What this contract does not claim

- It does not predict information that becomes known after the capture. Availability and
  the player projection are frozen at the first target gameweek; only the captured
  fixture calendar varies across the horizon.
- It does not model price changes, injuries, or postponements over the horizon.
- It does not carry uncertainty; scenario-aware multi-week planning is a later stage and
  will extend, not reinterpret, this handoff.
