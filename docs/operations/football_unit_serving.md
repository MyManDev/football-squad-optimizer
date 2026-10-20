# Compact unit inference

The exporter serves fitted pooled v4 parameters with physical exposure, source
missingness, raw identity policies and fixed alpha 0.1. The compact result has a
separate type from the full training result
(`src/squadopt/prediction/football_unit_serving.py:127`,
`src/squadopt/prediction/football_unit_serving.py:425`).

## Producer and reader

Verify the retained original fit receipt and model bytes, then call
`export_unit_serving_model(model, original_fit_sha256=..., target_season=..., target_gameweek=...)`.
The explicit target is the intended first forecast week. It is supplied by the
producer, not inferred from the last observed training row. V2 validates that all
training scopes precede this target and records actual released-season use. The
original fit digest remains producer provenance; the pure exporter and reader do
not reaudit original training sources
(`src/squadopt/prediction/football_unit_serving.py:56`,
`src/squadopt/prediction/football_unit_serving.py:225`,
`src/squadopt/prediction/football_unit_serving.py:425`).

V2 retains coefficients, applied and observed training scales, vocabulary,
attribute definitions and source families, fit cutoff, training scopes, explicit
target and exact policies. It requires the expected SHA256 and canonical JSON.
The reader accepts legacy v1 bytes without adding null target fields or changing
their digest; those older receipts retain their original release-option meaning
and make no v2 target declaration
(`src/squadopt/prediction/football_unit_serving.py:78`,
`src/squadopt/prediction/football_unit_serving.py:200`,
`src/squadopt/prediction/football_unit_serving.py:508`,
`src/squadopt/prediction/football_unit_serving.py:516`).

The reader rejects duplicate or unknown JSON fields, noncanonical bytes,
unsupported policy identities, Boolean numerical parameters, nonfinite values,
incorrect feature order, inconsistent scales and malformed source definitions.
Bounds remain 4 MiB, 10,000 vocabulary identities and 512 attribute definitions
(`src/squadopt/prediction/football_unit_serving.py:53`,
`src/squadopt/prediction/football_unit_serving.py:177`,
`src/squadopt/prediction/football_unit_serving.py:493`).

## Current prediction

Provide a current `UnitProjection` and its own source records. V2 accepts its
explicit target week and later weeks in that same season. It refuses earlier
weeks, another season, historical replay, a fit after the decision, same or future
training weeks, and changed attribute definitions or provider identities
(`src/squadopt/prediction/football_unit_serving.py:315`,
`src/squadopt/features/football_unit_inputs.py:801`).

Inference uses the same sparse encoder, scales and coefficients as the full model,
then exponential rates, native baseline multiplication and sorted state averaging.
It returns paired whole-fixture means, independently of the native focal minute
law. The receipt binds the artifact, original fit digest, projection, catalog and
attribute contract. Export alone does not activate a runtime bundle
(`src/squadopt/prediction/football_unit_serving.py:113`,
`src/squadopt/prediction/football_unit_serving.py:350`,
`src/squadopt/prediction/football_unit_serving.py:425`).
