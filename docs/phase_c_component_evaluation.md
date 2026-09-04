# Phase C component evaluation

Status: descriptive development result; operational control retained.

This report evaluates `phase_c_control_components_v1` on the same 147 chronological
development folds as the historical Ridge control. It uses the official autosub and
vice-captain scoring policy. The locked 2025-26 holdout was not read. The machine-readable
record is `phase_c_component_evaluation.json`.

## Source verification

- OOF table: 101,447 rows, SHA-256 `b05f10c3fd3ab5058fe1ff720cc6ef0a4b1362a70a19dd979ad0eb0f47d12c01`.
- Decision roster: 101,447 exact-key rows, SHA-256
  `3ef0c5717fa63c3c4772512f019cd750d3fae6cd9a7567d20dd4bfa24003678e`.
- Producer commit: `a43c0ec558f43750cf9311eabd14c216c27a3014`, clean tree.
- The producer environment was Python 3.11.0, NumPy 2.4.6, pandas 3.0.5,
  SciPy 1.17.1 and scikit-learn 1.9.0.

An independent reconstruction under NumPy 2.5.2 and SciPy 1.18.0 produced the same keys,
schema, missing-value masks, categorical values, roster digest and per-fold rankings. Eleven
`expected_minutes_if_appearance` cells differed by approximately `1e-9`; no other numeric
column differed and no per-fold top-15 set changed. The binding evaluation uses the producer's
verified table rather than replacing it with the reconstruction.

## Player-level diagnostics

The component route covers 100,130 rows; 1,317 thin-history rows use the declared direct-control
fallback.

| Metric | Result |
| --- | ---: |
| Appearance Brier score | 0.10734 |
| Appearance log loss | 0.35402 |
| Appearance mean calibration bias | -0.00172 |
| Minutes MAE, unconditional | 16.6788 |
| Minutes RMSE, unconditional | 26.0748 |
| Points MAE, unconditional | 1.09027 |
| Points RMSE, unconditional | 2.06009 |

The archive has no verified start labels, so start and conditional-start metrics have zero
observations. Missing is recorded as unavailable and is not replaced with a minutes proxy.

## Decision-level comparison

All 147 folds are feasible and scored for both arms.

| Result | Historical Ridge control | Component base |
| --- | ---: | ---: |
| Mean realized squad score | 58.5442 | 63.1633 |
| Optimal solves | 126 | 114 |
| Feasible, not proven optimal | 21 | 33 |
| Zero-minute selected starters | 75 | 83 |
| Autosub points | 187 | 220 |
| Vice-captain recoveries | 8 | 5 |

The paired component-minus-control difference is **+4.6190 points per gameweek**, with median
`+2.0` and a win/tie/loss count of **84/8/55**. The season means are positive in every
development season:

A post-run contract review added the manifest, model and environment identities to the stored
provenance. It did not recompute or change any fold, metric or decision result.

| Season | Mean paired difference |
| --- | ---: |
| 2021-22 | +4.7297 |
| 2022-23 | +6.9167 |
| 2023-24 | +2.5405 |
| 2024-25 | +4.3514 |

## Interpretation and exit state

This is a positive descriptive development association between the component decomposition and
realized decision scores. It is not a promotion result: no candidate-specific
numerical gate was frozen before this run, and 21 control plus 33 component solves were feasible
without a proof of optimality under the ten-second solver limit. The current operational model
therefore remains unchanged.

The Phase C component-base evaluation foundation is complete: the model, exact-key handoff
reader, player metrics, official-rule decision comparison, evidence-ablation boundary and
reproducible runner are in place. Phase C remains open for availability, ownership-transfer and
elite incremental-value measurements; those claims are prospective because
only deadline-valid future evidence can close those measurements honestly. The first Top-100
evidence handoff exists, but its target outcome was not settled at the time of this report.

No probability from this work is member-facing. Phase D may consume these component outputs,
but any published distribution still requires its own calibration gates.
