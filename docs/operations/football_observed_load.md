# Observed non-PL workload model

`ObservedLoadModel` fits an optional reweighting of a supplied whole-week native minute
distribution from named observed non-PL player records. Its input, feature and model versions
are separate from the complete all-competition workload model
(`src/squadopt/features/football_observed_load.py:32`,
`src/squadopt/prediction/football_observed_load.py:37`,
`src/squadopt/features/football_load_inputs.py:350`).

## Prepare source facts

Build immutable `ObservedLoadRecord` values for an exact persistent person. Each record names
its fixture and competition, reported minutes or unknown, independently confirmed starting
status or unknown, original source line and hash, and the original revision where that match
was observed finished. The source contract refuses duplicate person-match records, Premier
League records and facts without a completion bound before feature use
(`src/squadopt/features/football_observed_load.py:54`,
`src/squadopt/features/football_observed_load.py:186`).

`completed_by` means "observed finished by this original revision". It is not an invented
final-whistle time. The producer must retain and verify the original finished row, revision,
recording time and bytes. Today's final result alone cannot establish that earlier observation.
If the original evidence is unavailable, report the record as unavailable for this contract.
The reader checks the declared ordering, revision syntax and manifest binding; it does not
authenticate Git or fetch and compare those external source bytes
(`src/squadopt/features/football_observed_load.py:163`,
`src/squadopt/features/football_observed_load.py:168`,
`src/squadopt/features/football_observed_load.py:186`).

Retain separate source revision, source recording, retrieval, generation and feature-cutoff
clocks. A `public_revision_replay` can acquire historical source material later than its
reference decision. Its native original revision and history still precede feature use.
A `prospective` input must be prepared before feature use. Operator source-use evidence is
an explicit declaration; the validator does not infer an upstream data licence from it
(`src/squadopt/features/football_observed_load.py:71`,
`src/squadopt/features/football_observed_load.py:186`).

The complete native Premier League calendar is a separate requirement. Supply its original
revision and source hash, seven-state fixture supports, the complete canonical Cartesian
weekly inventory, correlated joint probabilities, exact marginal probabilities and joint-law
digest. A blank gameweek is one empty state. The new contract reuses the native-law validator
without constructing a complete-coverage `LoadWeek`
(`src/squadopt/features/football_observed_load.py:85`,
`src/squadopt/features/football_observed_load.py:186`,
`src/squadopt/features/football_load_inputs.py:251`,
`tests/unit/test_football_observed_load.py:402`).

## Observed feature scope

The fixed 24-feature inventory has eight entries for each 7, 14 and 28-day window: observed
record count, known and unknown minute counts, sum of known reported minutes, known and
unknown start counts, sum of confirmed starts and hours since the latest observed positive
minute record's kickoff. No known values makes a sum unknown. An empty observed population
has zero records, not a claim that the player played no matches
(`src/squadopt/features/football_observed_load.py:37`,
`src/squadopt/features/football_observed_load.py:324`,
`tests/unit/test_football_observed_load.py:188`).

The scope names its source competitions and records. Reported minutes, confirmed starts and
missing values remain distinct. These features do not supply physical minutes, added time,
travel, full-competition rest, national-team completeness or a future non-PL schedule.
The most recent observed positive kickoff is not necessarily the player's latest match
(`src/squadopt/features/football_observed_load.py:32`,
`src/squadopt/features/football_observed_load.py:54`,
`src/squadopt/features/football_observed_load.py:324`).

## Fit and inspect

`read_observed_load_snapshot` and `read_observed_load_outcome` accept supplied immutable
JSON bytes and their expected SHA256. They reject extra fields, duplicate JSON keys and
malformed array inventories. They perform no file or network operations
(`src/squadopt/features/football_observed_load.py:434`,
`src/squadopt/features/football_observed_load.py:491`,
`src/squadopt/features/football_load_inputs.py:212`).

Call `ObservedLoadModel.fit` with an explicit cutoff and target season/gameweeks. Reading or
training on released 2025-26 requires `allow_released_2025_26=True`; the default is false.
All population, source and outcome headers are checked before any row's minute/start labels.
Target and later training weeks, duplicate player/weeks and conflicting decision clocks
are refused. Labels must agree with the independent FPL minute/start bins and have positive
native support
(`src/squadopt/features/football_observed_load.py:155`,
`src/squadopt/features/football_observed_load.py:359`,
`src/squadopt/features/football_observed_load.py:401`,
`src/squadopt/prediction/football_observed_load.py:294`).

Decision and deadline must both lie in the declared season's UTC interval, from July 1
inclusive to the following July 1 exclusive. This also applies to blank weeks with no native
fixtures. The outcome reader checks its header clocks before converting label arrays
(`src/squadopt/features/football_observed_load.py:186`,
`src/squadopt/features/football_observed_load.py:491`).

The transform learns means and scales only from observed training values. It pairs each
numeric term with a missing indicator. A newly observed prediction feature without observed
training support is refused. Seven heads describe weekly appearance and the six active
minute bins through their counts in each weekly state. The categorical likelihood tilts the
whole native distribution; it does not multiply independently fitted fixture marginals
(`src/squadopt/prediction/football_observed_load.py:127`,
`src/squadopt/prediction/football_observed_load.py:140`,
`src/squadopt/prediction/football_observed_load.py:160`,
`src/squadopt/prediction/football_observed_load.py:178`).

The tilt preserves structural zeros and refuses numerical loss of positive native support.
Its joint law determines both weekly appearance and fixture marginals. Zero coefficients
recover the normalized native distribution, including its dependencies. Fitted coefficients
can change those dependencies through joint reweighting. No eligibility adjustment is applied
(`src/squadopt/prediction/football_observed_load.py:72`,
`src/squadopt/prediction/football_observed_load.py:218`,
`src/squadopt/prediction/football_observed_load.py:395`,
`tests/unit/test_football_observed_load.py:370`).

Metadata binds feature names, transforms, coefficients, source/input/outcome receipts and
observed competition scopes. A failed refit leaves the prior model intact. Prediction requires
a prospective source, the fitted target and a trained competition scope. This standalone
module needs a separate reviewed caller and verified real source preparation before live use
(`src/squadopt/prediction/football_observed_load.py:72`,
`src/squadopt/prediction/football_observed_load.py:230`,
`src/squadopt/prediction/football_observed_load.py:294`,
`src/squadopt/prediction/football_observed_load.py:395`).

Publishing a fit requires a Boolean success flag, integer successful status, integer iteration
count within the configured limit and finite real coefficients within the fixed bounds.
Missing or contradictory optimizer receipts are refused before replacing any fitted model
(`src/squadopt/prediction/football_observed_load.py:243`,
`src/squadopt/prediction/football_observed_load.py:294`).
