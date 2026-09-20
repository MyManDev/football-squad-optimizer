# Appearance recalibration v1 — frozen declaration

M5 of [#749](https://github.com/MyManDev/football-squad-optimizer/issues/749). This declares
one post-projection candidate, `appearance_recalibration_v1`, before any candidate fold is
read. The implementation and tests may be developed using synthetic data; the first real
run must name the commit containing this document and verify its SHA-256. No field below
may be selected after seeing the run. Existing aggregate records motivated the experiment;
this is not a claim that its development population is previously unseen.

## Inputs and refusal before measurement

Use only the existing `phase_c_component_oof_v1` CSV, its exact-key decision roster and
manifest. The reader validates their checksums, source identities, chronology and keys.
The manifest must declare no locked-holdout access; development seasons must be exactly
2021–22, 2022–23, 2023–24 and 2024–25. A v2 development manifest, dirty producer identity,
changed schema or a holdout declaration refuses before hashing or opening the table or
roster. Do not discover or regenerate an alternative artifact because its result differs.
Record the three input digests and producer commit even if the table differs from the
older `phase_c_component_evaluation` digest. There must be **147** decisions, in declared
chronological order. Refuse missing, duplicate or extra decisions.

The existing decision preparation uses the historical Ridge fallback on thin-history rows.
If that preparation needs the archive, pass only the explicit history tuple
`(2020-21, 2021-22, 2022-23, 2023-24, 2024-25)` to the existing adapter and only the four
development seasons to its walk-forward builder. Never use its default all-season loader.
**2025–26 is never opened, listed or hashed.** No model fitting outside the frozen fallback
construction, new source, new dependency or live capture is authorized here.

Before accepting any real inputs, require this committed declaration, the expected gate
fingerprint below, a clean runner commit and absent output files. Create an exclusive
attempt marker under the local artifact output directory before reading real rows. The
marker identifies the declaration/runner and prevents a second automatic attempt. A crash
or incomplete input records a refusal/failure, not an invitation to try a variant. Diagnose
without another measurement; a repeat needs an explicit new decision.

## Exact candidate

For each decision `d`, process all its rows as one held-out block. Eligible calibration
rows have `composition_route == component_model`, positive fixture count, finite original
appearance probability `p` in [0,1], finite conditional points and finite control points,
and binary `appearance_target`. A component row violating a numeric/target contract refuses
rather than silently shrinking the sample. Direct-control rows never fit the calibrator.

Fit a **single global increasing isotonic regression**, squared-loss objective, unit row
weights, `y_min=0`, `y_max=1`, `out_of_bounds=clip` (the already installed scikit-learn
`IsotonicRegression`). Training consists of eligible rows from decisions strictly before
`d`, across the four development seasons in chronological order. Equal input probabilities
are handled by that estimator's ordinary pooled weights. No position, price, club,
prior-minutes bucket, time decay, clipping floor, search or blend is added.

Use the identity map until there are at least **eight earlier decisions with eligible
rows**, at least **200 earlier eligible rows**, and both target classes in those rows.
Thereafter predict `p_calibrated = isotonic(p)` for eligible rows of `d`. The score is
`p_calibrated * expected_points_if_appearance`. Append `d`'s observations to training only
after its predictions are fixed. Future labels and other rows in `d` never fit its map.
The earliest folds therefore remain in the judged population with identity predictions.
For every direct-control/thin-history row use the exact same prepared fallback as the base
arm. Blank rows retain zero. Do not calibrate start probability, conditional points or minutes.

## Populations and readings

- **Brier and reliability:** eligible component rows only, all 147 decisions including
  identity warm-up. Report the same-row original and calibrated Brier, their difference,
  count and per-season readings. Report fixed probability bins [0,.1), …, [.9,1], count,
  mean prediction and observed appearance separately for each arm; empty bins are absent
  readings, not zero observed rate. The older Brier **0.10734** is a named historical
  reference, not a substitute for the paired base on this run's actual eligible rows.
- **Point error and rank:** the full prepared decision rosters, identical keys in both
  arms, all four seasons, all GK/DEF/MID/FWD positions, including unchanged fallbacks and
  blanks. Use the existing official realized points for these rows. Report row/fallback/
  blank counts. Error is all-row MAE; within-position Spearman uses average ranks for ties,
  separately per season and pooled. A constant vector gives an undefined correlation,
  recorded as missing evidence. No position or season may be dropped to pass the gate.
- **Forecast mass on nonplayers:** sum predicted points for realized zero-minute players
  divided by total predicted points on the same full rosters, for both arms, pooled and
  per season. A zero denominator is unavailable, not zero mass. This is a diagnostic,
  not an extra threshold chosen after seeing it.
- **Decisions:** base is the prepared frozen component forecast, candidate differs only
  by the transformation above. Solve both with `measurement_optimization_config()` and
  score under the existing official autosub policy on identical rosters/outcomes. Keep
  all 147 paired decisions, with OPTIMAL/FEASIBLE and clock-stop diagnostics. A missing
  pair or a clock-truncated result makes decision evidence insufficient; never gate on
  only the convenient pairs. Report wins/ties/losses and changed squads descriptively.

The paired difference interval is the existing season-aware moving-block bootstrap,
**90%**, **2,000 resamples**, **block length 4**, **base seed 0**, with the existing helper adding the first eight SHA-256 hex digits of
`appearance_recalibration_v1` as an integer to that base seed, sampling decisions within
each season and aggregating their paired differences. Use the same draws for the two arms,
not independent arm confidence intervals. Report per-season paired means too.

## Binding gate and failure path

Use `prediction_ranking_gate_v1` as defined in [the gate template](prediction_ranking_gate.md).
Its default policy fingerprint is
`798c82f567e97874b98055277ae5ced42b1916c2a568258b59553ad2cb613f11`:

- equally weighted pooled within-position rank gain at least **0.01**; no seasonal or
  pooled position loses more than **0.01**;
- all-row MAE at most **1.05 × control**, pooled and in every judged season;
- paired realized mean gain at least **0.5**, paired interval lower endpoint **>0**,
  at most **one** losing season, at least **two** judged seasons (this candidate declares four).

All clauses must pass. A known failed clause means `fails`; otherwise a missing clause
means `insufficient`. The record must keep the separate clause readings. Lower Brier does
not override a failed decision gate. No alternative calibrator, binning, warm-up, population
or threshold is tried after the verdict. A failed/insufficient scientific verdict still
completes M6 when honestly recorded. An execution refusal must instead identify what could
not be measured; it is not a scientific candidate failure or a passing run.

Inclusive nonzero numeric comparisons allow only absolute floating-point roundoff of
`1e-12` (relative tolerance zero). Zero-control MAE has no positive error allowance, and
the interval's strictly positive lower endpoint receives no tolerance. This comparison
rule is fixed before the run along with the thresholds; it is not a practical-effect margin.

Write `docs/appearance_recalibration.json`, its Markdown twin and a measurements-index row.
Record declaration digest/commit, policy digest, runner clean commit, source digests, solver
configuration, software versions, counts and verdict. No private host/user/path or credential
identity belongs in the public artifact. Never overwrite an existing record.

This fits and gates on 2021–25 scoring without DEFCON. It establishes no performance claim
for live DEFCON scoring, no top-100 ability, and no operational promotion. M7 makes that
limitation prominent in the programme agenda and index.
