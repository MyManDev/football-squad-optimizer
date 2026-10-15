# Compact unit inference

The compact contract serves the already fitted pooled v4 unit model through a
separate result type. Its exporter accepts only the physical exposure, source
missingness and raw identity policies with fixed alpha 0.1; the ordinary full
training result remains a different type
(`src/squadopt/prediction/football_unit_serving.py:394`,
`src/squadopt/prediction/football_unit_serving.py:123`,
`src/squadopt/prediction/football_unit_strength.py:292`).

## Producer and reader

The producer verifies the retained original fit receipt and model bytes, then
calls `export_unit_serving_model(model, original_fit_sha256=...)`. The digest
argument records producer provenance. The pure exporter and reader do not
reaudit original training sources. The reader requires the caller's expected
artifact SHA256 and canonical JSON bytes
(`src/squadopt/prediction/football_unit_serving.py:54`,
`src/squadopt/prediction/football_unit_serving.py:394`,
`src/squadopt/prediction/football_unit_serving.py:470`).

The parameter body retains coefficients, applied scales, observed training
scales, player vocabulary, attribute definitions and source families, fit
cutoff, training season and gameweek scope, and the exact objective and exposure
policies. It contains no observation records or model pickle. Immutable tuples
hold the parameters, and construction verifies their canonical digest
(`src/squadopt/prediction/football_unit_serving.py:76`,
`src/squadopt/prediction/football_unit_serving.py:278`).

The reader rejects duplicate or unknown JSON fields, unsupported policies,
noncanonical bytes, Boolean numerical parameters, nonfinite values, incorrect
feature order, inconsistent scales and malformed source definitions. Transport
bounds are 4 MiB, 10,000 vocabulary identities and 512 attribute definitions.
Identity scales must equal one; shared scales must equal their retained
training scales. FM game vintage remains unknown
(`src/squadopt/prediction/football_unit_serving.py:51`,
`src/squadopt/prediction/football_unit_serving.py:172`,
`src/squadopt/prediction/football_unit_serving.py:455`).

## Current prediction

Supply a current `UnitProjection` with its own source records and actual
decision clock. The compact predictor refuses historical replay, a fit after
the decision, the same or a future training gameweek, and changed attribute
definitions or source provider identities
(`src/squadopt/features/football_unit_inputs.py:761`,
`src/squadopt/prediction/football_unit_serving.py:290`).

Full v4 and compact inference share the same sparse feature encoder. The
compact path preserves sparse scaling, coefficient multiplication, exponential
rates, native baseline multiplication and sorted state averaging. It returns
paired whole-fixture means; it does not establish a joint native focal minute
law. The result receipt binds the parameter artifact, original fit digest,
projection, current catalog and attribute contract
(`src/squadopt/prediction/football_unit_strength.py:146`,
`src/squadopt/prediction/football_unit_strength.py:759`,
`src/squadopt/prediction/football_unit_serving.py:109`,
`src/squadopt/prediction/football_unit_serving.py:290`).

The serving tests cover exact full-model parity, multiple states, neutral
references, paired reversal, independent log-ratio arithmetic, missing source
attributes, unseen player identities, source and temporal refusals, immutable
parameters and malformed transport. Existing unit tests retain their legacy
metadata checks
(`tests/unit/test_football_unit_serving.py:44`,
`tests/unit/test_football_unit_serving.py:61`,
`tests/unit/test_football_unit_pooled.py:1`).

Export and inference alone do not activate a runtime bundle or establish a
forecast accuracy benefit. Runtime integration must consume the distinct
serving result explicitly and retain its receipt
(`src/squadopt/prediction/football_unit_serving.py:123`,
`src/squadopt/prediction/football_unit_serving.py:394`).
