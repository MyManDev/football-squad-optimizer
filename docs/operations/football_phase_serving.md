# Compact phase serving parameters

`export_phase_serving_model` produces canonical JSON bytes from a fitted phase model.
`read_phase_serving_model` accepts those bytes and an explicit expected SHA256.
The caller retains and reads files; these functions take model objects or bytes
(`src/squadopt/prediction/football_phase_serving.py:304`,
`src/squadopt/prediction/football_phase_serving.py:354`).

The artifact contains exact recipient coefficients, feature names, phase credit counts,
fitting-group counts, versions, declared fitting population, hyperparameters and target
window. It also contains the canonical full training metadata SHA256. Full observation
and source receipts stay in the original training metadata, outside this compact artifact
(`src/squadopt/prediction/football_phase_serving.py:51`,
`src/squadopt/prediction/football_phase_serving.py:304`).

The expected artifact digest must come from the caller's independently retained byte
receipt. A matching digest establishes byte integrity relative to that value. It does
not authenticate a publisher, establish historical availability, verify an external
source, or prove that the original training metadata was read. The original metadata
digest is a provenance reference. Restore checks the supplied artifact bytes and its
declared contract only (`src/squadopt/prediction/football_phase_serving.py:1`,
`src/squadopt/prediction/football_phase_serving.py:354`).

The reader refuses noncanonical JSON, duplicate or unknown fields, an unexpected
digest, artifacts above 65,536 bytes, incompatible versions or features, nonfinite
parameters, inconsistent head counts, duplicate heads, invalid seasons and an invalid
fitting cutoff. The restored arrays use immutable byte storage. No decoder constructs
empty training receipts to impersonate the full fitted metadata
(`src/squadopt/prediction/football_phase_serving.py:112`,
`src/squadopt/prediction/football_phase_serving.py:129`,
`src/squadopt/prediction/football_phase_serving.py:235`,
`src/squadopt/prediction/football_phase_serving.py:354`,
`src/squadopt/prediction/football_phase_duties.py:157`).

Both fitted and serving models call the same allocation function. State order,
recipient exposure, empirical phase composition, full-club conservation, unsupported
positive-mass refusal and each player's goal-plus-assist physical bound remain in
that function. The fitted model returns its existing full metadata; the serving model
returns `PhaseServingAllocation` with a distinct `serving_receipt`, including artifact
and original metadata hashes. Its prediction carries no full training archive
(`src/squadopt/prediction/football_phase_duties.py:490`,
`src/squadopt/prediction/football_phase_duties.py:529`,
`src/squadopt/prediction/football_phase_serving.py:77`,
`src/squadopt/prediction/football_phase_serving.py:88`,
`src/squadopt/prediction/football_phase_serving.py:272`).

These interfaces supply pure phase inference. Runtime bundle validation, combined
family scoring and activation are separate caller work; the serving path directly
returns allocation moments and its receipt
(`src/squadopt/prediction/football_phase_serving.py:272`).

The focused checks compare every aggregate and per-state player value, preserve
the original serialized metadata and allocation, exercise nonzero recipient effects
and zero phase support, and reject rehashed semantic changes and physical-bound
violations (`tests/unit/test_football_phase_serving.py:53`,
`tests/unit/test_football_phase_serving.py:108`,
`tests/unit/test_football_phase_serving.py:233`,
`tests/unit/test_football_phase_serving.py:311`).
