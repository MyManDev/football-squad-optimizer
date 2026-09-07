# Phase E development evaluation under the conditional residual sampler

Status: method record written before any E2 or E3 measurement under this sampler. It is not a
preregistration amendment and authorizes no binding measurement, no E4 shadow arm and no
production pin. It states which frozen rules a development run reuses unchanged and which
development scope is added, so that a later reader can tell the two apart.

## Why a separate identity

`docs/phase_e_candidate_selection_prereg.md` fixes the scenario sampler as the foundation
component sampler (`component_scenario_foundation_v1`). The binding Phase D run under that
sampler recorded `failed` (S1 passed, S2 failed), so the production pin
`PHASE_E_CALIBRATED_VERSIONS` is empty and E4 stays closed. The opt-in conditional residual
sampler (`component_scenario_conditional_residual_v1`, `ConditionalResidualConfig`) passed the
same S1 and S2 gates in a development measurement on the 137 seen folds; that report carries
`phase_d_component_squad_calibration_candidate_v1` and `binding: false`, and it is not
independent validation.

Measuring E2 and E3 under the conditional sampler is therefore development work outside the
frozen preregistration. Everything produced under it must be impossible to mistake for the
binding measurement:

| Artifact | Binding (foundation sampler) | Development (conditional sampler) |
| --- | --- | --- |
| Phase D evidence | `phase_d_component_squad_calibration_binding_v1` | `phase_d_component_squad_calibration_candidate_v1`, `binding: false` |
| E2 probe | `phase_e_runtime_probe_v2` | `phase_e_runtime_probe_development_v1`, `development_only: true`, `sampler` block |
| E3 evaluation | `phase_e_shadow_evaluation_v1` | `phase_e_shadow_development_v1`, `binding: false`, `e4_permitted: false` |

The binding E3 loader and the E4 hook accept only the left column. The development E3 runner
accepts only the right column, and only when the Phase D candidate evidence, the E2 artifact
and every draw name the same sampler and the same settings. Checkpoints of an E2 run are bound
to a run identity (sampler and settings, candidate counts, seeds, budget, scoring flag, Phase C
digests, producer commit); a directory holding another identity's checkpoints is refused, so
old-sampler partial work can never be counted as new-sampler work.

## Reused unchanged

- The 137-fold binding population, its burn-in and its direct-control abstention.
- Candidate generation: `generate_squad_candidates` with `OptimizationConfig()` defaults (10 s
  wall-clock CP-SAT, one search worker, seed 0, the lexicographic tie-break), no-good exclusion
  of complete `(squad, XI, captain)` decisions, `OPTIMAL`-only completeness.
- The E2 rule: K in {4, 8, 16}, all three measured, K=4 hard disable, bit-for-bit generation,
  draw and selection repeatability, the 120 s generation-plus-scoring budget, seeds 1 to 4 for
  the outcome-free seed-sensitivity diagnostic, the three original live pools as
  generation/diversity diagnostics whose scoring stays unavailable.
- The scorer (`score_component_scenario_decision`, `official_autosub_captain_v2` with
  `optimizer_projection_order_v1` completion), the integer mean/CVaR utility (ρ = 0.25,
  α = 0.10, N = 1000), the selection rule and its fallbacks, the coverage rule.
- The E3 gates A, R, U and S with the same season-aware moving-block policy and thresholds,
  and the verdict order.
- `ScenarioConfig()` defaults: 1000 scenarios, seed 0, eight history folds.
- The production pin stays empty. The selector reads the pin the caller supplies; the
  development runner supplies `(model_version, declared sampler)` only when the candidate
  evidence status is `calibrated_internal`, exactly as the binding runner does with the
  binding evidence.

## Added for development

- Explicit sampler selection on the E2 probe and the E3 runner (`--sampler conditional`
  with both conditional residual settings), threaded into every draw. A run never mixes
  samplers: the probe-only pin, the E3 pin, the draw identity and the fold records all carry
  the sampler the draw declares.
- Per-pool checkpoints and a coordinator status file for the E2 probe, with atomic writes
  retried on the transient Windows sharing error, optional process workers (one CP-SAT search
  worker and one BLAS thread per process), a resume that reuses only complete checkpoints of
  the same identity, named failures, and an artifact written only when every pool completed.
  The artifact records the worker count and whether timings came from an isolated process.
- The development E3 runner reads candidate Phase D evidence instead of the binding artifact
  and writes the development contract above.

## What a development result can and cannot say

A development E2 that freezes a K, and a development E3 whose verdict reads
`shadow_eligible`, describe the conditional sampler on the 137 seen folds. They do not
authorize E4, do not populate the production pin, and do not replace the binding `failed`
verdict. The prereg's prospective live-readiness gate and a reviewed amendment naming the
conditional sampler remain necessary before any of that. Numbers from these runs stay local
until their publication is authorized.

Two limits carried over from the binding path apply here too. The controls are re-solved in
every run under a wall-clock budget, so a fold whose solve stops `FEASIBLE` may freeze a
different decision in another run, and the frozen K rule reads such a fold as unproven; this is
a property of the budget, not of the sampler. And realized-score equality between runs is a
necessary condition for identical decisions, never a proof, because artifacts before this
change carry no decision identity for the Phase D control.

## Phase C/D v2 inputs

The explicit `--phase-c-contract development_v2` path reads the equal-weight A reference
through the existing v2 reader, pinned by `--expected-table-sha256`,
`--expected-roster-sha256` and `--expected-manifest-sha256`. This extends the development
population to the declared v2 seasons, including 2025-26. It does not change the v1
137-fold path, the sampler settings, the candidate counts, utility, budget or acceptance
thresholds. These are development readings on seen data.

E2 uses `--all-development-folds` for the complete population, or `--fold` for an explicit
pilot. Each pool is prepared with decision-week outcomes masked. History eligibility
uses only earlier residual rows; direct-control abstention is determined by a full-pool
control solve. Failed controls are named failures. A pilot never establishes the complete
eligible population and cannot freeze K. Full preparation includes those control solves
in its reported duration; it is not free preprocessing. The original three live captures
remain generation diagnostics and are not backfilled.

The probe writes `phase_e_runtime_probe_development_v2`; its source, full/eligible/measured
fold lists and exclusions join the sampler, worker/BLAS settings and producer revision in
checkpoint identity. A v1 checkpoint or a different v2 reference cannot be resumed as this
run. The fold rule uses the complete declared v2 eligible population rather than the old
137 constant. A partial or failed record is not a completed measurement.

E3 requires `--phase-d-development` naming a complete
`phase_d_component_squad_calibration_development_v2` record, the same three pinned inputs,
and the matching conditional sampler. A pilot, unverified fidelity, omitted/unsolved/unscored
fold, changed reference or conflicting sampler is refused. The recorded D verdict is
recomputed from its fold readings against its declared `verdict_population_fold_ids`,
which must equal the complete measured population. The handoff independently supplies history eligibility
again, and E2 must name that same population and development provenance. Before scoring,
each regenerated E3 control must equal D's complete recorded decision identity. A mismatch
is a named error; equal realized totals alone do not establish equal decisions.

The experiment-only selector in `scripts._phase_e_development` preserves provenance and
uses the existing candidate validation, official scorer, integer utility, coverage and
first-rank tie rule. The production selector and member-transfer core continue refusing
development draws even under a matching model/sampler pin. The E3 result and aggregate use
`phase_e_shadow_development_v2`, with `binding: false`, `e4_permitted: false` and honest
holdout-access metadata. The default scorer/aggregate still refuse 2025-26 without the
explicit development contract. A development result cannot enter E4 or change the pin.

## Member transfer application connection

Phase E generates complete squads from the full pool. The member advice path plans transfers
from a held squad under bank, free-transfer, hit and chip rules. A full-pool E2/E3 result says
nothing about that path. The core connection for scoring transfer candidates on one shared
component draw (`squadopt.scenarios.transfer_decisions`) keeps those rules, applies the
transfer hit once, and carries its own small validation plan; it makes no claim about the
public mode names.

The application accepts an optional local diagnostic hook around its already-solved
single-week saf-puan control. With no reviewed pin or no hook it does not adapt candidates,
generate a menu, draw scenarios or score alternatives. With both, the hook can supply
existing planner alternatives and one eligible draw to the transfer core and record the
returned diagnostic internally. The result never replaces the advice payload or adds a
public field; member-transfer promotion still requires its own evidence.
