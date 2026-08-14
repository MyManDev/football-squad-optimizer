# Live Recommendation Risk Diagnostics

## Decision boundary

The live squad continues to be selected by the promoted operational control. Risk
diagnostics score that already-frozen squad over residual scenarios; they do not change the
optimizer, the selected squad, the XI, the captain, or any promotion gate.

The contract is `live_recommendation_risk_v1`. The containing recommendation report is
`live_recommendation_v3`.

## Evidence policy

Risk metrics are available only when all of these conditions hold:

- residual model name, version, feature-contract version, and post-processing contract
  exactly match the projection that selected the live squad;
- the residual history contains the minimum declared number of out-of-sample folds;
- every residual row passes the existing hierarchical scenario contract;
- residual folds precede the target;
- for a GW1 target, the eligible rows are historical GW1 rows.

The last rule is explicit: gameweek-two-and-later residuals do not support opening-week
risk. They come from a different information regime and are excluded, not pooled with GW1.
If no historical GW1 residual exists, the report returns structured unavailable evidence
instead of a number.

## Structured states

`LiveRiskDiagnostics.status` is one of:

- `available`: every requested metric is supported;
- `unavailable`: risk was requested, but one or more evidence gates failed;
- `not_requested`: no residual history was supplied.

An unavailable result carries one or more machine-readable blockers:

- `model_mismatch`;
- `unsupported_opening_gameweek`;
- `insufficient_history`.

Metrics and a scenario fingerprint are forbidden on unavailable/not-requested results. The
text renderer prints the reasons and the statement that no lower-tail number was produced.

## Available metrics

The existing fixed-decision scenario evaluator supplies:

- the declared lower quantile score;
- mean score in the declared worst tail fraction;
- strict probability that score is below the declared threshold;
- scenario count and scenario fingerprint.

The captain is counted twice and bench points are excluded, matching the frozen realized
scoring policy. The decision is never reoptimized per scenario.

## Provenance

Every requested calculation records:

- residual source ID;
- full input and eligible-subset SHA-256 fingerprints;
- residual model and feature identity;
- post-processing identity, including the captured availability rule;
- input and eligible row counts;
- exact eligible fold IDs;
- target gameweek and GW1 filtering policy;
- scenario seed/count/minimum-fold controls;
- quantile, tail-fraction, and threshold controls.

The live projection now also carries a fingerprint and cutoff for the completed historical
panel supplied to the opening control. This lets the temporary `PredictionSnapshot` used by
scenario generation name its actual training input rather than inventing provenance.

## Command

The default command still works without risk evidence and reports `not_requested`:

```powershell
python -m scripts.recommend_current_squad
```

To request risk diagnostics, every residual identity field is explicit:

```powershell
python -m scripts.recommend_current_squad `
  --risk-residuals artifacts/control_opening_residuals.csv `
  --risk-model-name squadopt-deterministic-baseline `
  --risk-model-version opening-carry-over-v1 `
  --risk-feature-contract-version opening-carry-over-features-v1 `
  --risk-post-processing-contract-version captured_availability_rule_v1 `
  --risk-source-id control-opening-oos-v1 `
  --risk-min-history-folds 8 `
  --risk-scenario-count 1000 `
  --risk-seed 0 `
  --risk-lower-quantile 0.10 `
  --risk-worst-fraction 0.10 `
  --risk-points-threshold 40
```

Until a matching historical opening-week residual export exists, the expected live state is
`unavailable`, not a synthetic substitute derived from midseason folds.
