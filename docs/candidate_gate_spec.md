# Declared Candidate Gate Contract

## Purpose

Issue #43 changes one part of the projection model: the expected-points rate. The
development comparison must not become an opportunity to tune the model, the optimizer,
or the gate after seeing the response. This contract makes the declaration a typed,
fingerprinted input to the benchmark and checks the declaration against the provenance of
every candidate prediction snapshot.

The gate still measures the frozen single-gameweek decision objective. Multi-gameweek
transfer planning is a downstream consumer and is not a replacement evaluation objective
for this candidate.

## Declaration before execution

Construct a `CandidateDeclaration` before running the benchmark. For the Issue #43
candidate it records:

- `changed_component = "expected_points_rate"`;
- a learned rate fitted only on the expanding training slice;
- fixture count, home/away counts, appearance rate, and minutes per appearance as the
  declared rate inputs;
- the minutes stage, cold-start ladder, availability rule, two-stage combination,
  feature windows, shrinkage weights, opening-price coefficient, optimizer contract, and
  promotion gates as frozen components;
- `evaluation_objective = "single_gameweek_realized_squad_points_v1"`;
- Issue #43 as the source reference.

The model name, model version, and feature-contract version in that declaration must equal
the values carried by every returned `PredictionSnapshot`. A plain `DataFrame`, a missing
provenance field, or a different version stops the run instead of producing gate evidence.

Both the declaration and the complete `ProductionBenchmarkConfig` receive SHA-256
fingerprints. Changing any declaration, fold, solver, Ridge, control, gate-policy, or run
metadata input therefore creates a different benchmark identity.

## Frozen comparison

The candidate, deterministic baseline control, and Ridge reference are evaluated in one
process on the same walk-forward folds. The development seasons remain 2021-22 through
2024-25; 2025-26 remains locked. All seven pre-registered conditions in
`production_prediction_spec.md` remain unchanged.

The current reproducible control run is context, not a target for the future candidate:

- 147 paired folds;
- baseline mean realized squad score 53.2585;
- current production mean 57.7483;
- Ridge mean 57.1020;
- current production minus baseline +4.4898, 90% interval [2.5643, 6.6939];
- current production minus Ridge +0.6463, 90% interval [-1.6194, 2.9524];
- verdict `no_promotion_control_retained`.

The failed current-production conditions are the Ridge lower bound and the relative
prediction-metric tolerance. These numbers must not be copied into a new result; all three
candidates are remeasured together under the same deterministic solver-work contract.

## Execution sequence

1. Review and freeze the candidate declaration and benchmark configuration fingerprints.
2. Build the candidate with no further model or hyperparameter changes.
3. Run `run_declared_candidate_benchmark` exactly once for the formal development result.
4. Serialize the result; the report includes both fingerprints and the declared change.
5. Treat a passing development verdict only as eligibility for the locked-holdout
   protocol, never as automatic operational promotion.

Synthetic tests and smoke runs may precede step 3. They are not gate evidence and may not
read the locked holdout.
