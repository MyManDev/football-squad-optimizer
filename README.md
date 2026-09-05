# SquadOpt Product Roadmap

This roadmap tracks the path from a correctly measured deterministic optimizer to a
calibrated, evidence-aware and multi-gameweek football decision-support system.

## Current position

- **Phase A — Engineering complete; prospective evidence accumulating.**
- **Phase B — Complete.** The deadline-safe evidence layer is built and its first real
  handoff is produced and verified.
- **Phase C — Engineering ready; merge and deployment pending.** The component model,
  decision-level evaluation and live-default integration are prepared in PRs #348, #350 and
  #351. They remain outside `develop` and production until the deadline freeze ends and the
  stacked release is revalidated.
- **Phase D — Foundation under review; decision scoring in progress.** PR #349 introduces the
  pre-registered appearance-plus-paired-residual sampler without changing Scenario V1 or live
  behaviour. Contract hardening, official scenario scoring, correlation and calibration remain.
- **Phases E–H — Planned.** Later phases do not become product claims until their own
  calibration and evaluation gates pass.

## Phase A — Measurement correctness

**Status: engineering complete; live evidence accumulating.**

Goal: ensure that system quality is measured under real game rules before changing the model.

- Apply official autosub ordering and legal post-substitution formations.
- Apply vice-captain recovery when the captain does not play.
- Score the bench, captain multiplier and settled outcomes consistently.
- Replace the unconstrained ownership XI with a budget-, position- and team-feasible template.
- Compare V1 and V2 on identical historical decisions and outcomes.
- Freeze prospective strong-manager cohorts before their target deadlines.

Recorded result:

- Settled GW1 parity: **11/11 exact matches**, maximum absolute difference `0.0`.
- Paired development benchmark: **147 folds** over 2021-22 through 2024-25.
- Mean template-minus-system gap: **5.796 under V1**, **3.871 under V2**.
- Paired gap change: **-1.925 points per gameweek**.
- The result is season-dependent and descriptive because historical ownership timing is not
  verified.
- The GW3 Overall Top-100 cohort is frozen; its outcome remains pending settlement.

Exit state: engineering work is complete. Prospective evidence continues to accumulate for at
least eight gameweeks, with twelve or more preferred for a stable-season interpretation.

## Phase B — Deadline-safe evidence layer

**Status: complete.**

Goal: provide the player model with information that was genuinely available before each
decision deadline.

- Capture nested Top-50, Top-100 and Top-200 elite cohorts without replacing the frozen Phase A
  primary Top-100 cohort.
- Capture overall ownership and transfer-in/transfer-out movement.
- Capture official availability fields and their decision timestamps.
- Use only lagged elite picks: gameweek `N` picks cannot be evidence for a gameweek `N`
  decision.
- Preserve persistent player identity across seasonal element IDs.
- Record `captured_at_utc`, deadline, snapshot IDs, checksums and timing verification.
- Distinguish missing evidence from a genuine zero.
- Keep manager identities and raw captures outside committed artifacts.
- Produce one deterministic player-by-decision evidence table for Phase C.

Recorded result:

- The first real handoff: **629 player rows for 2026-27 gameweek 3**, built from a Top-200
  standings capture taken **72.88 hours** before the deadline and gameweek 2 elite picks.
- **100/100** cohort members readable, **0** missing picks, **0** unmapped elements.
- Internal consistency holds: squad counts sum to 1500, starting counts to 1100, captain
  shares to 1.000.
- The export is deterministic and create-once; the record is in
  [`phase_b_evidence_contract.md`](docs/phase_b_evidence_contract.md).
- The cohort is the **sensitivity** Top-100 cut from the Top-200 capture. The frozen Phase A
  primary Top-100 is a different cohort and carries the benchmark claims.

Exit criteria:

- Every feature satisfies the time-of-knowledge contract.
- Top-50/100/200 membership is deterministic and deadline-frozen.
- Missingness, privacy and provenance are explicit and tested.
- Phase C can consume the evidence table without importing data-source adapters.

## Phase C — Probabilistic player model

**Status: engineering ready; merge and deployment pending the deadline freeze.**

Goal: replace a single undifferentiated point estimate with explicit, testable components.

- Estimate probability of any appearance.
- Estimate probability of starting.
- Estimate minutes conditional on appearing.
- Estimate points conditional on minutes, fixture and role.
- Compose the components into an expected-points distribution.
- Keep a control fallback when optional evidence is unavailable.
- Evaluate appearance with calibration and Brier score.
- Evaluate minutes with out-of-sample error metrics.
- Evaluate points and final squad decisions on chronological walk-forward folds.
- Ablate ownership, elite, transfer and availability evidence separately before combining them.

The first operational slice is intentionally narrower than the final component model. It uses
the previous-gameweek Top-100 XI count as a bounded five-per-cent uplift to the existing
in-season expected-points handoff, while live availability remains a separate, single
post-processing step. The exact rule, rollback and limitations are frozen in
[`docs/phase_c_operational_elite_policy.md`](docs/phase_c_operational_elite_policy.md).

No probability from this phase is member-facing. Publication requires the later scenario and
calibration gates.

Delivery state:

- PR #348 provides the versioned component targets, models and reproducible out-of-fold handoff.
- PR #350 provides the chronological component and decision-level evaluation record.
- PR #351 makes the component projection the live default with an explicit legacy fallback.
- The three-PR stack is not yet on `develop` or in production. It must be merged in order and
  exercised through the live replay and deployment runbooks after the freeze.

Exit criteria:

- Component models are leakage-safe, versioned and reproducible.
- Each evidence family has a separate incremental-value measurement.
- The candidate improves decision-level outcomes under pre-registered gates or the control is
  retained.

## Phase D — Monte Carlo V2

**Status: foundation under review; decision-level integration in progress.**

Goal: generate realistic joint player and squad outcomes from the Phase C model.

- Model appearance as a mixture rather than a continuous score adjustment.
- Represent heavy tails and asymmetric downside.
- Preserve player correlations within teams and fixtures.
- Add team, fixture and gameweek common shocks.
- Handle blank and double gameweeks.
- Apply autosubs, bench order and vice-captain recovery inside every scenario.
- Re-run squad-level location and lower-tail calibration.

Current delivery state:

- PR #349 pre-registers and implements the first component-aware sampler: a Bernoulli
  appearance mixture followed by paired conditional minutes and points residuals.
- The foundation does not yet provide official per-scenario autosubs, vice-captain recovery,
  honest fallback for direct-control rows, calibrated common/team shocks or a live promotion.
- The next delivery reuses the Phase A official scorer to evaluate one frozen squad decision
  inside every component scenario; it does not create a second game-rules implementation.

Exit criteria:

- Scenario means reproduce the point model.
- Realized squad scores pass the declared location and lower-tail gates.
- Scenario claims remain internal when calibration fails.

## Phase E — Stochastic single-gameweek optimizer

**Status: pre-registered; engine not yet written.**

Goal: choose one legal squad decision using calibrated uncertainty rather than only mean points.

- Optimize expected score under the unchanged legal squad constraints.
- Measure downside with CVaR or another pre-registered coherent risk measure.
- Value the bench through appearance-driven autosub contribution.
- Price captain risk explicitly.
- Support rival-gap utility without mixing rival identity into the player model.
- Give Saf Puan, Garantici and aggressive modes measured mathematical meanings.

Current delivery state:

- `docs/phase_e_candidate_selection_prereg.md` freezes the first Phase E design before any
  production code: a candidate-based selector, not a scenario-aware optimizer. The
  deterministic CP-SAT model proposes the top-K decisions over the full pool (identity:
  squad, starting eleven and captain, exact no-good constraints, every candidate proven optimal),
  every candidate is scored on one shared Phase D component draw with the official scorer,
  and a fixed integer mean/CVaR utility (rho 0.25, alpha 0.10, 1000 scenarios) selects, with
  named fallbacks to the Phase C control. E2 measures repeatability and seed sensitivity;
  E3 uses season-aware moving-block uncertainty for historical shadow evaluation.
- Legacy boundary: `optimize_scenario_aware_squad` and its config and result types are
  legacy. They are not on the live path, are not a fallback, receive no new features, and
  are scheduled for removal after E5 behind an audit of the recorded artifacts that depend
  on them.
- Not yet delivered: the candidate generator, the selector, the E2 runtime probe, the E3
  shadow evaluation and the live shadow seam. The rival-gap utility and the mode meanings in
  the goals above are later Phase E work with their own preregistrations.

Exit criteria:

- Every mode has a frozen objective and reproducible price.
- No mode is named safer or more aggressive without passing its declared evidence gates.
- The risk-neutral arm remains a reproducible control.

## Phase F — Multi-gameweek rolling horizon

**Status: planned.**

Goal: plan transfers over three to five gameweeks while re-optimizing at every deadline.

- Maintain squad continuity, bank, free transfers and transfer hits.
- Track chip state and squad value without inventing future prices.
- Use a versioned projection horizon and scenario tree.
- Define a measured terminal value.
- Separate the live one-gameweek control from longer research horizons.
- Re-plan after every new capture instead of treating one plan as permanently optimal.

Exit criteria:

- One-week output reproduces the single-gameweek control.
- State transitions follow the game rules exactly.
- Longer horizons beat or justify their cost against the rolling one-week control.

## Phase G — Design of Experiments and Bayesian Optimization

**Status: planned after the model and objectives stabilize.**

Goal: search expensive policy and model choices without tuning against noise or the locked
holdout.

- Use DoE to identify important factors and interactions.
- Freeze candidate spaces and evaluation budgets before optimization.
- Use Bayesian Optimization only for the reduced, versioned search space.
- Track evaluation noise and optimizer regret against tractable grid references.
- Evaluate multiple objectives through explicit trade-offs or Pareto frontiers.
- Reserve the locked holdout for one declared promotion decision.

Exit criteria:

- Search choices are reproducible and development-only.
- Candidate promotion requires pre-registered decision-level gates.
- A failed gate closes or revises the hypothesis through a new preregistration, not a silent
  rerun.

## Phase H — Advanced methods and product scaling

**Status: future.**

Goal: introduce more complex methods only when simpler calibrated baselines leave a measured
gap.

- Consider sparse or Student-t Gaussian processes for non-Gaussian and larger-scale settings.
- Consider state-space or hidden Markov models for role and availability transitions.
- Consider approximate dynamic programming or MCTS for larger planning state spaces.
- Consider reinforcement learning only after a trustworthy simulator and offline evaluation
  policy exist.
- Add LLM-derived evidence last, as structured and time-stamped evidence rather than as an
  autonomous squad selector.
- Scale to multiple leagues and users after the decision system is stable end to end.

Exit criteria:

- Every advanced method must beat a simpler baseline on a frozen evaluation contract.
- LLM evidence must retain source, capture time, confidence and provenance.
- Product scaling must not weaken reproducibility, privacy or probability-publication gates.
