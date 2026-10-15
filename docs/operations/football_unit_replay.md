# Historical unit replay for the experimental football model

Use the typed historical replay contract when reconstructing a club unit training
catalog from an original public FPL revision and a published frozen FM feature
version acquired later. The receipt records the original revision, public record
time, actual retrieval, historical feature cutoff and actual reconstruction time.
FM game or save vintage remains `unknown`.
(`src/squadopt/features/football_unit_inputs.py:200`)

## Prepare the historical basis

1. Retain the exact original bytes and SHA256 values for `players_raw.csv`,
   `teams.csv`, `fixtures.csv`, `gws/merged_gw.csv`, the FM export under the receipt
   key `fm.csv`, and the generated native baseline under `native_baseline.json`.
   Supply those pairs through `UnitHistoricalReplay.source_hashes`.
   (`src/squadopt/features/football_unit_inputs.py:237`)
2. Set `recorded_at` from the original public Git revision and `retrieved_at` from
   the actual acquisition of its `gws/merged_gw.csv`. Historical input must satisfy
   `latest_history_kickoff < recorded_at <= feature_cutoff <= decision_cutoff`,
   with history settled more than three hours before the feature cutoff. Actual
   retrieval follows the historical decision and precedes or equals generation.
   (`src/squadopt/features/football_unit_inputs.py:259`,
   `src/squadopt/features/football_unit_inputs.py:279`)
3. Keep three distinct source identities. The reference source uses version
   `git:<revision>`, the original history CSV hash, its recorded publication and
   actual retrieval. The FM source uses the exact export hash and its own actual
   acquisition time. The baseline source uses the generated artifact hash, actual
   generation for both publication and capture, and the historical feature cutoff
   as its effective time. FM and reference publication and effective times must
   precede or equal the feature cutoff. These effective times describe feature
   eligibility; the replay does not authenticate an FM save date.
   (`src/squadopt/features/football_unit_inputs.py:266`,
   `src/squadopt/features/football_unit_inputs.py:303`)
4. Supply complete actual and reference units with active persistent player and
   club mappings. Each unit contains eleven distinct players and one goalkeeper.
   Preserve published FPL scoring positions. They are distinct from tactical
   roles. Missing FM attributes remain missing and receive explicit missingness
   features in the model.
   (`src/squadopt/features/football_unit_inputs.py:160`,
   `src/squadopt/features/football_unit_inputs.py:182`,
   `src/squadopt/features/football_unit_inputs.py:583`,
   `src/squadopt/prediction/football_unit_strength.py:737`)

The historical catalog may set `projection_source_id=None` when it carries its
typed replay receipt. Additional sources still pass the ordinary availability
check. A current `UnitProjection` refuses historical replay and requires a
projection source identity.
(`src/squadopt/features/football_unit_inputs.py:489`,
`src/squadopt/features/football_unit_inputs.py:314`,
`src/squadopt/features/football_unit_inputs.py:761`)

## Bind reported exposure and fit explicitly

Each replay observation requires `UnitExposureClock`, including the outcome
artifact SHA256, exact source interval identity and selection evidence reference.
Its version is `reported_first_half_minute_bins_0_to_40_v1`. Start and duration
must be integer minute coordinates within zero through forty. The hash must match
the outcome source. These are reported minute bins, with no exact physical second
claim.
(`src/squadopt/features/football_unit_inputs.py:320`,
`src/squadopt/features/football_unit_inputs.py:667`)

Construct `FootballUnitStrengthModel` only after the reconstructed features and
settled outcome receipts exist. For an explicitly released 2025-26 training
population, use the boolean argument shown below. Its default remains `False`.
The constructor rejects reused interval identities, overlapping fixture intervals
and differing decision cutoffs within one gameweek.
(`src/squadopt/prediction/football_unit_strength.py:334`,
`src/squadopt/prediction/football_unit_strength.py:401`,
`src/squadopt/prediction/football_unit_strength.py:409`)

```python
model = FootballUnitStrengthModel(observations, cutoff=fit_cutoff, allow_released_2025_26=True)
```

Retain the resulting fit contract and receipts. Historical prefix replay uses
`football_unit_public_replay_quantized_prefix_fit_v1`. Explicit season release
without replay uses `football_unit_explicit_release_fit_v1`. The former records
the clock, source selection, unknown FM vintage and the assumption that whole
match rates extrapolate associations fitted on selected first half prefixes.
The numerical exposure offset remains `minutes / 90 * baseline`.
(`src/squadopt/prediction/football_unit_strength.py:472`,
`src/squadopt/prediction/football_unit_strength.py:517`,
`src/squadopt/prediction/football_unit_strength.py:641`)

## Verify before composition

The experiment result boundary rechecks replay source bindings, clocks, interval
identity, overlap, shared gameweek decision cutoff and exclusion of the target or
future gameweek. Current projection still requires its own complete supplied unit
states. The native focal minute law remains independent of those supplied unit
states in this model version.
(`src/squadopt/experiments/football_unit_experiment.py:91`,
`src/squadopt/features/football_unit_inputs.py:779`,
`src/squadopt/prediction/football_unit_strength.py:953`)

The legacy version one JSON boundary accepts the new optional fields only when
they are null. Build historical replay through the typed records. Regression
tests cover source clock separation, missing FM attributes, replay tampering,
target population checks, unchanged legacy fingerprints and unchanged serialized
legacy result metadata.
(`src/squadopt/features/football_unit_catalog.py:169`,
`src/squadopt/features/football_unit_catalog.py:304`,
`tests/unit/test_football_unit_replay.py:192`,
`tests/unit/test_football_unit_replay.py:362`,
`tests/unit/test_football_unit_replay.py:397`,
`tests/unit/test_football_unit_replay.py:418`)
