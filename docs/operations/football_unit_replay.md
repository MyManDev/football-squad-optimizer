# Historical unit replay for the experimental football model

The typed replay keeps the public revision, original record time, actual retrieval,
historical feature cutoff, actual generation and unknown FM game vintage distinct.
New replay v2 also requires the native baseline fit SHA256 and its training cutoff;
that cutoff must not follow the historical feature cutoff
(`src/squadopt/features/football_unit_inputs.py:201`,
`src/squadopt/features/football_unit_inputs.py:229`).

## Prepare the historical basis

Retain exact SHA256 values for `players_raw.csv`, `teams.csv`, `fixtures.csv`,
`gws/merged_gw.csv`, `fm.csv` and `native_baseline.json`. Bind the native fit digest
and cutoff from the verified baseline's own fitted-model receipt. These fields
are declarations checked for consistency; the typed model does not independently
read or authenticate the source files
(`src/squadopt/features/football_unit_inputs.py:219`,
`src/squadopt/features/football_unit_inputs.py:257`).

The original revision must already hold settled history:
`latest_history_kickoff + 3 hours < recorded_at <= feature_cutoff <= decision_cutoff`.
Retrieval follows the historical decision and does not follow generation. FM
publication and effective time must be known by the feature cutoff, while its
actual acquisition stays after the decision. Reference publication equals the
original record time and capture equals retrieval. Baseline publication and
capture equal generation; its effective time equals the feature cutoff. Reference
and baseline validity covers the decision and expires strictly before retrieval
(`src/squadopt/features/football_unit_inputs.py:278`,
`src/squadopt/features/football_unit_inputs.py:285`,
`src/squadopt/features/football_unit_inputs.py:303`).

For FM, call `read_scoped_fm_attributes(..., cutoff=decision_cutoff, replay=replay)`.
It validates the original CSV bytes, uses replay admission for the later FM capture
and selects mappings at that historical decision. Keep the returned receipt intact.
Build the historical catalog with its three source receipts, ordinary mappings,
empty FM attribute definitions and rows, and the same replay; then call
`scoped.add_to_catalog(catalog, attributes=specs)`. The handoff requires the exact
same decision and replay, and permits the identical FM source already needed by
the replay catalog. An independently supplied catalog remains supported; manually
splitting the scoped receipt discards its checked handoff
(`src/squadopt/features/football_fm_attributes.py:213`,
`src/squadopt/features/football_fm_attributes.py:265`,
`src/squadopt/features/football_fm_attributes.py:296`,
`tests/unit/test_football_unit_replay_guards.py:39`).

Additional sources pass normal availability checks. Historical catalogs may omit
a projection source, but naming one does not make a replay eligible for current
projection. The expiry rule also prevents reuse of the original reference and
baseline after retrieval merely by dropping the replay field
(`src/squadopt/features/football_unit_inputs.py:351`,
`src/squadopt/features/football_unit_inputs.py:540`,
`src/squadopt/features/football_unit_inputs.py:801`).

## Exposure, release and result evidence

The owner explicitly authorized 2025-26 training for the experimental football
model in the task conversation on 2026-10-16, accepting that the season loses its
independent test status. The public record of that decision is the owner-training
disclosure in the description of
[PR #1120](https://github.com/MyManDev/football-squad-optimizer/pull/1120).
This paragraph records that user decision; it is not a GitHub reviewer approval
or authorization for a new accuracy measurement.

Reported prefix exposure requires an exact source interval identity and selection
reference, with integer minute coordinates in 0 through 40. Physical exposure has
its separate seconds and past-duration contract; neither policy is silently
substituted for the other
(`src/squadopt/features/football_unit_inputs.py:359`,
`src/squadopt/features/football_unit_inputs.py:383`,
`src/squadopt/features/football_unit_inputs.py:706`).

New fits require v2 replay receipts. The explicit `allow_released_2025_26=True`
argument authorizes that season for this fit; the emitted v2 release declaration
is true only when actual 2025-26 rows are present. Enabling the option without
such rows does not create a release-only contract. The default remains false
(`src/squadopt/prediction/football_unit_strength.py:343`,
`src/squadopt/prediction/football_unit_strength.py:423`,
`src/squadopt/prediction/football_unit_strength.py:485`).

The result boundary rechecks source identities, acquisition and fitting clocks,
exposure identity, fixture basis, nonoverlap, shared gameweek decision and exclusion
of target or later training weeks. It requires the exact exposure, extrapolation
and FM eligibility statements. Legacy v1 result contracts retain their original
option semantics, but their replay receipts must also satisfy the current timing
rules above. A previously accepted v1 receipt that violates those rules is refused;
v1 readability does not preserve its former admission behavior. V2 declarations
must match the actual exposure population. This is receipt validation, with no
forecast accuracy claim
(`src/squadopt/experiments/football_unit_experiment.py:98`,
`src/squadopt/experiments/football_unit_experiment.py:158`,
`src/squadopt/experiments/football_unit_experiment.py:402`).
