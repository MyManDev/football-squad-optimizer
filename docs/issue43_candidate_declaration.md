# Issue #43 Candidate Declaration — frozen before execution

Stage A of `docs/candidate_declaration_review.md`. Both fingerprints below are computed from the same typed objects the formal run constructs, so what is reviewed here is what executes. **No formal run has been made against this declaration.**

## Fingerprints

- Candidate: `learned_rate_calendar_candidate_v1`
- Declaration: `f72962a182e4d857448d860641c7ebc211a4f7101f3ed713362636fa2b3bce09`
- Benchmark configuration: `b64a3ab9f06f1c1a207d66c8f1d59b0c3072f7fe8400cb598e378fca37e6f575`

## The single changed component

`expected_points_rate`

The expected-points rate is fitted per fold on the expanding visible history instead of read straight from the shifted rolling points-per-90 feature. That feature remains an input, joined by fixture count, home fixture count, appearance rate, and minutes per appearance. Closed-form ridge on standardised inputs, solved with numpy, so the fit carries no seed, iteration count, or solver choice.

### Declared rate inputs

- `points_per_90_last_6`
- `appearance_rate_last_6`
- `minutes_per_appearance_last_6`
- `fixture_count`
- `home_fixture_count`

The first of these is the frozen rolling feature the replaced stage read directly. It stays an input because the handoff checklist freezes the feature windows: dropping it would change the feature mapping as well as the rate, which would be two changes rather than one. **If the intended reading was that the rate model may not see the player's own scoring history at all, this declaration is wrong and must be reissued before any run.**

## Identity

| Field | Value |
| --- | --- |
| `model_name` | `squadopt-learned-rate` |
| `model_version` | `learned-rate-v2` |
| `feature_contract_version` | `learned-rate-calendar-appearance-v1` |
| `training_contract_version` | `expanding_window_minutes_weighted_ridge_rate_v1` |
| `evaluation_objective` | `single_gameweek_realized_squad_points_v1` |

These strings appear unchanged in both residual manifests and in every returned `PredictionSnapshot`; the benchmark refuses the run if they differ.

## Frozen components

- `expected_minutes_stage`
- `cold_start_ladder`
- `availability_post_processing`
- `two_stage_combination`
- `feature_window_mapping`
- `shrinkage_weights`
- `opening_price_prior`
- `development_fold_set`
- `baseline_control`
- `ridge_reference`
- `optimization_contract`
- `budget_and_formation_constraints`
- `promotion_gates`
- `evaluation_objective`

## Stage A status

- Reviewed by the optimization/evaluation side: pending
- Reviewed by the architecture/CI side: pending
- Fingerprints frozen: pending

A change to anything above after the freeze voids it. There is no small-fix exception: a changed candidate is a new candidate with a new fingerprint.
