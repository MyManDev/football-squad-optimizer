# Compact score serving

The pure exporter accepts an already fitted score model and emits canonical JSON
containing its six coefficients, numerical settings, target and cutoff guards,
versioned policies and original metadata digest. It performs no fit and does not
include training observations or reconstruct training metadata
(`src/squadopt/prediction/football_score_serving.py:185`).

The caller supplies parameter bytes and their expected SHA256 to the reader.
It rejects payloads above 65,536 bytes, duplicate keys, noncanonical JSON, unknown
fields, unsupported policies, numeric Booleans, nonfinite values and malformed
vectors. The coefficient bounds and numerical tolerance match the original score
model. A matching supplied hash establishes byte integrity; it does not establish
source authenticity or permission. The original metadata digest is provenance,
with no claim that the loader checked the absent training sources
(`src/squadopt/prediction/football_score_serving.py:79`,
`src/squadopt/prediction/football_score_serving.py:97`,
`src/squadopt/prediction/football_score_serving.py:224`).

The loaded model holds frozen tuple parameters and validates its digest before
prediction. It checks the supplied fixture and preserves the original fitted
target-season, earliest-gameweek and decision-cutoff guards. Full and compact
prediction use the same numerical process. The compact result has a separate
serving receipt: its prediction digest identifies the compact artifact, while
the original full metadata digest is named separately. It does not impersonate
a full training result
(`src/squadopt/prediction/football_score_serving.py:59`,
`src/squadopt/prediction/football_score_serving.py:137`,
`src/squadopt/prediction/football_score_state.py:840`).

The tests compare full and compact process outputs exactly apart from that
deliberately distinct digest, cover explicit released-season replay provenance,
reject malformed or temporally invalid inputs, and independently check zero-chain
interval survival. These are implementation checks, with no accuracy or live
activation result (`tests/unit/test_football_score_serving.py:1`).
