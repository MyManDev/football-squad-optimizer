# Observed non-PL workload model

`ObservedLoadModel` fits an optional reweighting of a supplied whole-week native minute
distribution from named observed non-PL player records. Its input, feature and model versions
are separate from the complete all-competition workload model
(`src/squadopt/features/football_observed_load.py:32`,
`src/squadopt/prediction/football_observed_load.py:38`,
`src/squadopt/features/football_load_inputs.py:350`).

## Prepare source facts

Build immutable `ObservedLoadRecord` values for an exact persistent person. Each record names
its fixture and competition, reported minutes or unknown, independently confirmed starting
status or unknown, original source line and hash, and the original revision where that match
was observed finished. The source contract refuses duplicate person-match records, Premier
League records and facts without a completion bound before feature use
(`src/squadopt/features/football_observed_load.py:55`,
`src/squadopt/features/football_observed_load.py:209`).

`completed_by` means "observed finished by this original revision". It is not an invented
final-whistle time. The producer must retain and verify the original finished row, revision,
recording time and bytes. Today's final result alone cannot establish that earlier observation.
If the original evidence is unavailable, report the record as unavailable for this contract.
The reader checks the declared ordering, revision syntax and manifest binding; it does not
authenticate Git or fetch and compare those external source bytes
(`src/squadopt/features/football_observed_load.py:186`,
`src/squadopt/features/football_observed_load.py:191`,
`src/squadopt/features/football_observed_load.py:209`).

Retain separate source revision, source recording, retrieval, generation and feature-cutoff
clocks. A `public_revision_replay` can acquire historical source material later than its
reference decision. Its native original revision and history still precede feature use.
A `prospective` input must be prepared before feature use. Operator source-use evidence is
an explicit declaration; the validator does not infer an upstream data licence from it
(`src/squadopt/features/football_observed_load.py:72`,
`src/squadopt/features/football_observed_load.py:209`).

The complete native Premier League calendar is a separate requirement. Supply its original
revision and source hash, seven-state fixture supports, the complete canonical Cartesian
weekly inventory, correlated joint probabilities, exact marginal probabilities and joint-law
digest. A blank gameweek is one empty state. The new contract reuses the native-law validator
without constructing a complete-coverage `LoadWeek`
(`src/squadopt/features/football_observed_load.py:86`,
`src/squadopt/features/football_observed_load.py:209`,
`src/squadopt/features/football_load_inputs.py:251`,
`tests/unit/test_football_observed_load.py:405`).

## Observed feature scope

The fixed 24-feature inventory has eight entries for each 7, 14 and 28-day window: observed
record count, known and unknown minute counts, sum of known reported minutes, known and
unknown start counts, sum of confirmed starts and hours since the latest observed positive
minute record's kickoff. No known values makes a sum unknown. An empty observed population
has zero records, not a claim that the player played no matches
(`src/squadopt/features/football_observed_load.py:38`,
`src/squadopt/features/football_observed_load.py:366`,
`tests/unit/test_football_observed_load.py:191`).

The scope names its source competitions and records. Reported minutes, confirmed starts and
missing values remain distinct. These features do not supply physical minutes, added time,
travel, full-competition rest, national-team completeness or a future non-PL schedule.
The most recent observed positive kickoff is not necessarily the player's latest match
(`src/squadopt/features/football_observed_load.py:32`,
`src/squadopt/features/football_observed_load.py:55`,
`src/squadopt/features/football_observed_load.py:366`).

## Fit and inspect

`read_observed_load_snapshot` and `read_observed_load_outcome` accept supplied immutable
JSON bytes and their expected SHA256. They reject extra fields, duplicate JSON keys and
malformed array inventories. They perform no file or network operations
(`src/squadopt/features/football_observed_load.py:476`,
`src/squadopt/features/football_observed_load.py:536`,
`src/squadopt/features/football_load_inputs.py:212`).

Call `ObservedLoadModel.fit` with an explicit cutoff and target season/gameweeks. Reading or
training on released 2025-26 requires `allow_released_2025_26=True`; the default is false.
All population, source and outcome headers are checked before any row's minute/start labels.
Target and later training weeks, duplicate player/weeks and conflicting decision clocks
are refused. Labels must agree with the independent FPL minute/start bins and have positive
native support
(`src/squadopt/features/football_observed_load.py:178`,
`src/squadopt/features/football_observed_load.py:401`,
`src/squadopt/features/football_observed_load.py:443`,
`src/squadopt/prediction/football_observed_load.py:317`).

Decision and deadline must both lie in the declared season's UTC interval, from July 1
inclusive to the following July 1 exclusive. This also applies to blank weeks with no native
fixtures. The outcome reader checks its header clocks before converting label arrays
(`src/squadopt/features/football_observed_load.py:209`,
`src/squadopt/features/football_observed_load.py:536`).

The transform learns means and scales only from observed training values. It pairs each
numeric term with a missing indicator. A newly observed prediction feature without observed
training support is refused. Seven heads describe weekly appearance and the six active
minute bins through their counts in each weekly state. The categorical likelihood tilts the
whole native distribution; it does not multiply independently fitted fixture marginals
(`src/squadopt/prediction/football_observed_load.py:150`,
`src/squadopt/prediction/football_observed_load.py:163`,
`src/squadopt/prediction/football_observed_load.py:183`,
`src/squadopt/prediction/football_observed_load.py:201`).

The tilt preserves structural zeros and refuses numerical loss of positive native support.
Its joint law determines both weekly appearance and fixture marginals. Zero coefficients
recover the normalized native distribution, including its dependencies. Fitted coefficients
can change those dependencies through joint reweighting. No eligibility adjustment is applied
(`src/squadopt/prediction/football_observed_load.py:74`,
`src/squadopt/prediction/football_observed_load.py:241`,
`src/squadopt/prediction/football_observed_load.py:418`,
`tests/unit/test_football_observed_load.py:373`).

Metadata binds feature names, transforms, coefficients, source/input/outcome receipts and
observed competition scopes. A failed refit leaves the prior model intact. Prediction requires
a prospective source, the fitted target and a trained competition scope. This standalone
module needs a separate reviewed caller and verified real source preparation before live use
(`src/squadopt/prediction/football_observed_load.py:74`,
`src/squadopt/prediction/football_observed_load.py:253`,
`src/squadopt/prediction/football_observed_load.py:317`,
`src/squadopt/prediction/football_observed_load.py:418`).

Publishing a fit requires a Boolean success flag, integer successful status, integer iteration
count within the configured limit and finite real coefficients within the fixed bounds.
Missing or contradictory optimizer receipts are refused before replacing any fitted model
(`src/squadopt/prediction/football_observed_load.py:266`,
`src/squadopt/prediction/football_observed_load.py:317`).


## Captured native input and compact serving

For a current official capture, use the separate `ObservedLoadCapturedNativeBasis` with
`captured_snapshot_v1`, its original snapshot identity and full source fingerprint. It has
no Git revision field. The legacy revision-backed native schema remains unchanged. The
captured variant is prospective only and retains the same complete PL calendar, weekly
state inventory, marginal and history checks
(`src/squadopt/features/football_observed_load.py:86`,
`src/squadopt/features/football_observed_load.py:105`,
`src/squadopt/features/football_observed_load.py:209`,
`tests/unit/test_football_observed_load.py:703`).

Its recording clock is the original capture clock. Retrieval precedes actual native basis
generation, which precedes input generation and feature use. Native fit information also
precedes native generation. A later assembly of an existing captured native law must retain
its original fit-information cutoff and record the new assembly clock as
`native_generated_at`. The producer must verify the capture's payload checksums, full
fingerprint, roster and fixture bindings. The reader verifies the declared identity and
manifest binding; it does not open the external capture bytes
(`src/squadopt/features/football_observed_load.py:105`,
`src/squadopt/features/football_observed_load.py:209`,
`src/squadopt/features/football_observed_load.py:476`).

`export_observed_load_serving_result` exports only inference parameters, fitted target and
scope, and the full training metadata's SHA256 identity. The compact result has its own
version and byte digest. `read_observed_load_serving_result` requires the exact canonical
JSON bytes, checks field inventories, versions, finite bounded coefficients and transform
support, and creates an immutable model with no fit method. It does not read or verify the
absent full training metadata: publication must separately verify that exported parameters
match that retained metadata
(`src/squadopt/prediction/football_observed_load.py:112`,
`src/squadopt/prediction/football_observed_load.py:473`,
`src/squadopt/prediction/football_observed_load.py:498`,
`src/squadopt/prediction/football_observed_load.py:545`).

The compact model uses the same predictor as the fitted model, retaining target, scope,
missing-support and chronology checks. Single, double and blank gameweek tests require
identical fitted and served probabilities, marginals and native zero-coefficient results.
This serving primitive does not install a product caller or combine availability adjustments
(`src/squadopt/prediction/football_observed_load.py:427`,
`src/squadopt/prediction/football_observed_load.py:498`,
`tests/unit/test_football_observed_load.py:725`,
`tests/unit/test_football_observed_load.py:816`).
