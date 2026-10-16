# Compact observed tactical recipients

The `football_observed_tactical_recipient_serving_v2` artifact retains the two exact
recipient transforms and coefficient vectors, credited-event support counts, observation
count, training cutoff, target window, season permissions and explicit source/model
policies. The original full metadata SHA256 records provenance. Team-rate parameters
and observation receipts are outside this compact schema
(`src/squadopt/prediction/football_observed_tactical_serving.py:64`).

`export_observed_tactical_serving_model` requires the fitted observed-tactical model,
checks its original scope and exports canonical JSON. It also accepts the distinct
recipient-only model, retaining that model version and fit scope in the artifact. The original model's metadata
and inference results retain their existing receipt types
(`src/squadopt/prediction/football_observed_tactical_serving.py:329`,
`src/squadopt/prediction/football_observed_tactical.py:180`,
`src/squadopt/prediction/football_observed_tactical.py:750`).

`read_observed_tactical_serving_model` requires the expected SHA256 computed externally
over retained bytes. It refuses different bytes, noncanonical or repeated JSON fields,
unsupported policies, malformed dimensions, nonfinite or nonnumeric parameters,
inconsistent transform support and nonzero disabled columns. Its size bound is 262144
bytes. These are byte-integrity and declaration checks; the hash does not authenticate
the source, prove training happened, or independently verify the declared cutoff
(`src/squadopt/prediction/football_observed_tactical_serving.py:58`,
`src/squadopt/prediction/football_observed_tactical_serving.py:116`,
`src/squadopt/prediction/football_observed_tactical_serving.py:165`,
`src/squadopt/prediction/football_observed_tactical_serving.py:212`,
`src/squadopt/prediction/football_observed_tactical_serving.py:387`).

The compact model and original recipient-only API call the same conditional allocation
helper. It keeps persistent-player order, exact native zero support, finite normalized
shares, historical head support and the per-player physical goal fraction guard.
It does not evaluate the paired-rate head. Current projection clocks and the fitted
target window still apply; native control returns the supplied shares
(`src/squadopt/prediction/football_observed_tactical.py:426`,
`src/squadopt/prediction/football_observed_tactical_serving.py:285`).

The new allocation DTO carries a separate serving receipt with both artifact SHA256
and original metadata SHA256, plus the projection and supplied source hashes. These
identifiers distinguish the compact retained parameters from the full training record.
Final team rates, score dynamics and clean sheets remain responsibilities of a caller
that composes these recipient shares with its other validated families
(`src/squadopt/prediction/football_observed_tactical_serving.py:90`,
`src/squadopt/prediction/football_observed_tactical_serving.py:100`,
`src/squadopt/prediction/football_observed_tactical_serving.py:285`).

Tests compare every returned recipient share and native-control value, exercise
strict transform and byte refusals, and forbid count-head or original-model calls
during compact inference. They establish contract parity using invented fixtures,
without a predictive-accuracy or runtime-activation claim
(`tests/unit/test_football_observed_tactical_serving.py:1`).
