# Phase D Decision-Scoring Preregistration

Status: frozen before implementation; no measurement is authorized by this document.

## Claim

This step tests plumbing, not model quality: a squad decision frozen before a scenario draw
can be scored under every component scenario with the same normal-gameweek autosub,
formation and captain rules used by the settled Phase A scorer.

## Frozen procedure

1. Accept one feasible `OptimizationResult` and one component scenario draw.
2. Complete bench order and vice-captain exactly once from decision-time projections with
   `complete_optimization_decision`. Scenario outcomes must not affect that completion.
3. Never re-optimize or reorder the decision inside a scenario.
4. For each scenario, pass its sampled points and appearance state to
   `score_frozen_squad_decision`. This existing scorer remains the only implementation of
   normal-gameweek autosubs, legal post-substitution formations and vice-captain recovery.
5. Preserve scenario order and return one auditable `RealizedSquadScore` per scenario.
6. Require both point and appearance inputs for all 15 selected players. Extra player
   columns are allowed because the scenario draw normally represents the whole player pool.

The settled scorer requires integer minutes but uses only the distinction between zero and
positive minutes. The adapter therefore maps a validated appearance state to `0` or `1` and
does not claim that those integers are simulated match minutes.

## Fail-closed dependency

The component sampler must expose an unambiguous appearance state. A sampled appearance that
can later be clipped to zero minutes is not distinguishable from a non-appearance by looking
at `sampled_minutes` alone. Until the component-scenario contract either carries the sampled
appearance matrix or guarantees that every sampled appearance has positive minutes, the
decision scorer must reject ambiguous draws rather than infer an appearance.

The component draw identity must also bind all inputs that can change the score, including
sampled minutes or appearance state. A point-matrix-only fingerprint is insufficient for an
auditable autosub result. This requirement is owned by the component-scenario contract; this
step does not create a competing fingerprint.

## Explicit non-goals

- no scenario calibration, shift or dispersion adjustment;
- no risk metric, CVaR objective or scenario-aware re-optimization;
- no promotion, live default or member-facing probability;
- no double-gameweek scoring extension;
- no second implementation of Phase A game rules.

## Acceptance checks

- Bench order and vice-captain are frozen before scenario outcomes are read.
- Goalkeeper substitution, legal outfield substitution and bench-order skipping match the
  settled scorer.
- Captain fallback matches the settled scorer.
- Scenario identifiers and returned scores remain in the same order.
- Missing selected-player coverage and ambiguous appearance state are rejected.
- Caller-owned frames are not mutated.
