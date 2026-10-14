# Specifications

A specification states the contract of a component, its interface, inputs, outputs and
versioned names, or the design of a measurement, and is kept in step with the code it
describes. It is named `<name>_spec.md` ([naming key](../README.md#naming-key)). A protocol
fixed before a measurement runs is a pre-registration instead, and goes in
[`research/`](../research/README.md).

This folder is the home of new specifications. A new one is added here with a row under
[Specifications in this folder](#specifications-in-this-folder):
`tests/architecture/test_docs_root.py` refuses a new living document at the root of `docs/`, and
`tests/architecture/test_docs_reachable.py` requires a link to it.

## Specifications at the root of `docs/`

The sixteen specifications written before this folder existed stay at their paths. Two of them
are named as a `source_reference`: `candidate_gate_spec.md` in the committed record
`issue43_candidate_declaration.json`, and `production_prediction_spec.md` in the default
candidate declaration of `squadopt.backtest.production_benchmark`. The naming key says those two
never move.

| Specification | What it specifies |
| --- | --- |
| [Artifact preflight](../artifact_preflight_spec.md) | The checks a residual-export artifact passes before a measurement consumes it (`artifact_preflight_v1`) |
| [Bayesian policy search](../bayesian_optimization_spec.md) | The search over versioned policy configurations on chronological development folds; it recommends a candidate and promotes none |
| [Calendar-aware residual measurement](../calendar_recalibration_spec.md) | The comparison of calendar-blind and calendar-aware residuals on identical out-of-sample rows (`calendar_recalibration_measurement_v1`) |
| [Declared candidate gate](../candidate_gate_spec.md) | The typed, fingerprinted declaration of the issue #43 candidate, checked against the provenance of every candidate prediction |
| [Prepared-fold evaluation](../evaluation_spec.md) | The scoring of frozen single-gameweek squad decisions against later outcomes, on prepared folds |
| [Sprint 2 screening experiment](../experimentation_spec.md) | The screening design over `form_window` and `bench_weight` against the deterministic baseline (`screening_doe_v1`) |
| [Sprint 6 learned prediction](../learned_prediction_spec.md) | A ridge reference projection compared with the deterministic baseline on identical chronological folds (`ridge-reference-v1`) |
| [Live recommendation risk diagnostics](../live_risk_diagnostics_spec.md) | Risk diagnostics of an already-frozen live squad over residual scenarios (`live_recommendation_risk_v1`); they change no decision |
| [Sprint 0 optimization](../optimization_spec.md) | One gameweek's squad, starting lineup, bench and captain from supplied projections |
| [Sprint 5 prediction integration and player-adaptive uncertainty](../player_uncertainty_spec.md) | The hand-off from predictions to the optimizer (`prediction_to_optimization_v1`), still in `squadopt.prediction`; its uncertainty and screening contracts were removed on 2026-10-12 |
| [Production prediction](../production_prediction_spec.md) | What goes into the production prediction snapshot and why, with its pre-registered evaluation gates |
| [Sprint 4 conformal risk optimization](../risk_optimization_spec.md) | A risk-aware single-gameweek objective (`conformal_lcb_objective_v1`); the package was removed on 2026-10-12 and the document records the contract as it was |
| [Scenario-aware optimization](../scenario_optimization_spec.md) | One gameweek's decision chosen directly against joint point scenarios |
| [Sprint 7 Monte Carlo scenarios](../scenario_spec.md) | Joint outcome scenarios from out-of-sample residuals, and the evaluation of one frozen decision over them (`hierarchical_residual_scenarios_v1`) |
| [Deterministic transfer planning](../transfer_planning_spec.md) | A sequence of deadline decisions from projections and explicit transaction prices |
| [Sprint 3 projection uncertainty](../uncertainty_spec.md) | Uncertainty around the point projection (`projection_uncertainty_v1`); the package was removed on 2026-10-12 and the document records the contract as it was |

## Specifications in this folder

None yet.

[All documentation](../README.md).
