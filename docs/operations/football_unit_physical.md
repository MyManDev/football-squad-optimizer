# Physical exposure for the experimental club unit model

Select `physical_seconds_over_forecast_duration_v1` explicitly when fitting
complete observed matches with exact physical second intervals. This policy
requires the source missingness v2 features and declares model version
`football_projected_unit_physical_source_missingness_v3`. The default exposure
policy retains `minutes / 90 * supplied causal baseline`.
(`src/squadopt/prediction/football_unit_strength.py:49`,
`src/squadopt/prediction/football_unit_strength.py:218`,
`src/squadopt/prediction/football_unit_strength.py:496`)

## Prepare the source receipts

Build each `UnitPhysicalExposureClock` from an independently verified observed
interval. Supply exact integer start and end seconds, the actual complete match
duration, the outcome artifact SHA256, an interval identity and a selection
evidence reference. The declared clock version is
`pannadata_paired_periods_nonzero_event_seconds_fullmatch_v1`. Every interval must
lie within its actual match duration. Minute fields must equal the exact second
bounds divided by sixty; rounding those minute fields is refused.
(`src/squadopt/features/football_unit_inputs.py:20`,
`src/squadopt/features/football_unit_inputs.py:343`,
`src/squadopt/features/football_unit_inputs.py:613`)

Supply a separate causal duration forecast with policy
`past_verified_nonzero_period_end_seconds_arithmetic_mean_v1`. Retain its bytes,
the complete historical fixture population and the duration source evidence.
Bind their SHA256 values through the replay keys `duration_forecast.json`,
`duration_history.json` and `duration_clock_source.json`. The clock carries the
forecast minutes, historical season/gameweek/fixture identities, feature cutoff,
latest historical settlement bound, actual source acquisition time and actual
generation time. These fields bind the supplied evidence; the typed input does
not itself download source events or calculate the historical mean.
(`src/squadopt/features/football_unit_inputs.py:343`,
`src/squadopt/features/football_unit_inputs.py:430`)

The duration history must exclude the target fixture, the entire target
gameweek and future seasons. Its latest settlement bound must precede or equal
the original revision record, and its feature cutoff must equal the historical
replay cutoff. Actual duration source acquisition follows that cutoff and
precedes or equals duration generation. Duration generation cannot follow the
replay generation. Preserve those actual clocks when reconstructing older
features. A bound that states a match was observed finished by the original
revision can equal that revision time; it does not assert the final whistle time.
(`src/squadopt/features/football_unit_inputs.py:397`,
`src/squadopt/features/football_unit_inputs.py:430`)

## Fit with the correct offset

```python
model = FootballUnitStrengthModel(
    observations,
    cutoff=fit_cutoff,
    allow_released_2025_26=True,
    missingness_policy="source_all_unobserved_residual_v2",
    exposure_policy="physical_seconds_over_forecast_duration_v1",
)
```

Each match must have a complete contiguous interval partition from zero to its
actual duration. Intervals retain one common reference, native baseline,
catalog and duration forecast. Mixed physical and reported minute populations
are refused. The 2025-26 release remains an explicit boolean.
(`src/squadopt/features/football_unit_inputs.py:456`,
`src/squadopt/features/football_unit_inputs.py:464`,
`src/squadopt/prediction/football_unit_strength.py:218`,
`src/squadopt/prediction/football_unit_strength.py:277`)

For an interval of `s` observed seconds, forecast duration `d` minutes and
supplied native whole fixture mean `b`, the Poisson offset is
`s / (60 * d) * b`. Actual target match duration establishes interval coverage;
it is never the denominator. Train only scaling and fixed `alpha=0.1` remain in
place. Current prediction still multiplies the supplied whole fixture means by
reference relative unit effects. Identical projected and reference units remain
neutral. These are fitted observational associations.
(`src/squadopt/prediction/football_unit_strength.py:496`,
`src/squadopt/prediction/football_unit_strength.py:528`,
`src/squadopt/prediction/football_unit_strength.py:778`,
`tests/unit/test_football_unit_physical.py:222`,
`tests/unit/test_football_unit_physical.py:242`)

## Retain and validate the distinct version

Keep the fit contract `football_unit_public_replay_physical_duration_fit_v1`,
the complete replay and exposure receipts and a new actual fit cutoff. The
experiment boundary checks agreement between model, feature, fit and exposure
versions, all required clock fields, source hash bindings, temporal population
rules and complete physical partitions. It continues to bind attribute source
families to every historical and current source group. A current projection
still refuses a historical replay catalog.
(`src/squadopt/prediction/football_unit_strength.py:349`,
`src/squadopt/prediction/football_unit_strength.py:396`,
`src/squadopt/experiments/football_unit_experiment.py:83`,
`src/squadopt/experiments/football_unit_experiment.py:405`,
`src/squadopt/experiments/football_unit_experiment.py:513`,
`src/squadopt/features/football_unit_inputs.py:746`)

Synthetic contract tests cover the physical offset, exact seconds, history
exclusion, malformed source evidence, mixed clocks, missing intervals and
tampered result receipts. Existing regression tests retain the legacy input
fingerprints and frozen result metadata digest. These checks establish contract
behavior; they do not measure predictive improvement.
(`tests/unit/test_football_unit_physical.py:130`,
`tests/unit/test_football_unit_physical.py:179`,
`tests/unit/test_football_unit_physical.py:283`,
`tests/unit/test_football_unit_replay.py:362`,
`tests/unit/test_football_unit_replay.py:397`)
