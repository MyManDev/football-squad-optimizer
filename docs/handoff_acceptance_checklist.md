# Prediction Handoff Acceptance Checklist

## Purpose

The next prediction-side handoff (the #43 learned-rate candidate and its residual
exports) is accepted or rejected against this checklist. Each item names the expected
artifact and the concrete verification, so acceptance is a mechanical pass over evidence
rather than a judgement call. A failed item blocks the handoff; nothing is repaired or
reinterpreted on the receiving side.

Companion documents: [artifact preflight](artifact_preflight_spec.md),
[residual export contract](residual_export_contract.md),
[candidate gate](candidate_gate_spec.md),
[GW1 blocker report template](gw1_blocker_report_template.md),
[declaration review](candidate_declaration_review.md).

## Checklist

| # | Expected item | Verification |
| --- | --- | --- |
| 1 | Learned-rate candidate definition | Review: changed component is `expected_points_rate` only; expected-minutes stage, cold-start ladder, availability rule, two-stage product, feature windows, shrinkage controls, opening-price prior, optimizer contract, promotion gates, and evaluation objective are unchanged. |
| 2 | Candidate builder implementation | Code review plus the four quality gates below on the delivering branch; synthetic/smoke tests exercise the builder. |
| 3 | Model name and version | Identical strings in the `CandidateDeclaration`, both residual manifests' `model_name`/`model_version`, and the candidate `PredictionSnapshot` provenance. |
| 4 | Feature contract version | Same check as item 3 for `feature_contract_version`; must name a versioned contract compatible with `form_window_v1`. |
| 5 | Training contract version | Present in both manifests (`training_contract_version`); named in the declaration review. |
| 6 | Candidate `PredictionSnapshot` provenance | Snapshot carries model/feature/training identity and training cutoff; spot-check equality with manifest fields. |
| 7 | `form_window_v1` mapping verification | Statement plus passing tests that the frozen mapping (w → minutes/points/per-90 windows, min_periods=1) is applied unchanged. |
| 8 | Calendar-blind residual export | `python -m scripts.run_artifact_preflight --table <reference.csv> --manifest <reference.manifest.json> --expect-fold-count 147 --expect-row-count 101447 --expect-seasons 2021-22,2022-23,2023-24,2024-25` exits 0. |
| 9 | Calendar-aware residual export | Same command against the candidate export; plus the pair mode (`--reference-table/--reference-manifest`) exits 0. |
| 10 | Two manifests | Covered by items 8–9; retain both manifests and the preflight JSON record beside the reports. |
| 11 | Fixture/team bridge | `scripts.run_calendar_recalibration` with both `--*-manifest` arguments completes; the fixture join reports no unknown teams and non-empty fixture groups. |
| 12 | Historical GW1 residual feasibility analysis | Written analysis. If infeasible, a completed [GW1 blocker report](gw1_blocker_report_template.md) is the deliverable; #45 stays open on structured `unavailable`, and that is an accepted outcome. |
| 13 | BO-ready deterministic prediction builder | Implements `DevelopmentFoldPolicyEvaluator` (`squadopt.bayesopt.evaluation`); `bind_policy_evaluator` accepts it; a smoke search on synthetic data completes deterministically. |
| 14 | Prediction factor mapping | `form_window` passthrough documented; no factor is silently defaulted or ignored (the binding refuses both). |
| 15 | Candidate evaluation cost/runtime | Reported per-candidate wall time on the 147 development folds, with the machine and stopping rule named. |
| 16 | Quality gates | `pytest`, `ruff check`, `ruff format --check`, `mypy --strict src` all pass on the delivering branch; outputs recorded. |
| 17 | Declaration and config fingerprints | `declaration_fingerprint` and benchmark `configuration_fingerprint` computed, recorded, and frozen **before** the formal run, per the [declaration review](candidate_declaration_review.md). |

## Acceptance rule

Every applicable item passes, or the handoff is returned with the failed items named.
Item 12 may legitimately conclude "infeasible" — the completed blocker report is then
the accepted artifact. No other item has a degraded pass.
