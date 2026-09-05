# Phase D binding squad calibration

The single preregistered binding run returned **`failed`** on all **137/137** eligible
development folds. Location passes; the lower-tail gate fails. This is a completed
negative measurement, with no operational promotion.

| Frozen gate | Measured result | Acceptance interval | Outcome |
| --- | --- | --- | --- |
| S1: mean probability integral transform | 0.5144160584 | [0.43, 0.57] | Pass |
| S2: realized score below scenario q10 | 28/137 = 0.2043795620 | [0.04, 0.16] | Fail |

The realized squad score fell below its predicted tenth percentile in **20.44%** of
folds. This exceeds the preregistered upper bound of 16%. The location result alone
cannot establish calibration; the component scenario distribution is not eligible
for calibrated internal claims or Phase E4 live shadow use.

The [unaltered JSON record](phase_d_component_squad_calibration_binding.json) includes
the per-fold scores, distribution readings, fingerprints, population exclusions,
configuration, environment and source digests. Its SHA256 is
`2f36d8389f4966f8b8fd803114c29e2efe519ac12ca3dce5061f8b54ba21ede5`.
It is 81,521 bytes and contains no per-player source table or capture payload.

## Execution and provenance

- Preregistration: [frozen population and S1/S2 gates](phase_d_component_squad_calibration_prereg.md).
- Source revision: `f3bebc19944529073b8011f7da6f4adb76b4af55`, clean detached worktree,
  after C/D and binding runner #368 passed Python 3.11, Python 3.13 and web CI.
- One dispatch; 2026-09-05 18:36:38 to 19:03:46 UTC, elapsed 1628.2027 seconds.
  The JSON timestamps retain their equivalent `+03:00` offsets.
- Frozen Phase C table, roster, manifest and reviewed fidelity artifact were checked
  against their registered SHA256 values before launch and by the binding reader.
- Population: 147 OOF decisions, nine history burn-in folds and one additional
  direct-control abstention, leaving 137 folds from 2021-22-gw11 to 2024-25-gw38.
- Historical inputs: explicit 2020-21 through 2024-25 development allowlist.
  No locked 2025-26 holdout path was read, listed or hashed.
- Python 3.13.5, NumPy 2.5.2, pandas 3.0.5, SciPy 1.18.0,
  scikit-learn 1.9.0, OR-Tools 9.15.6755; no recorded warnings.

Command, with `FROZEN_INPUTS` pointing to the verified input package,
`DEVELOPMENT_ARCHIVE` to the archive root and `OUTPUT` to an ignored artifact directory:

```text
python -u -m scripts.run_component_squad_calibration --table FROZEN_INPUTS/phase_c_component_oof_v1.csv --roster FROZEN_INPUTS/phase_c_component_oof_v1.roster.csv --manifest FROZEN_INPUTS/phase_c_component_oof_v1.manifest.json --fidelity FROZEN_INPUTS/phase_d_component_fidelity.json --archive-root DEVELOPMENT_ARCHIVE --json-output OUTPUT/phase-d-binding.json
```

## Consequences

No shift, scale, threshold, scenario setting or population was changed in response,
and the binding run was not repeated. The original artifact remains unchanged.
Phase E2 may still measure runtime and determine K under its registered rule.
With a valid K, E3 may produce a **technical-only** historical evaluation using this
failed binding evidence. It cannot open E4. The production selector pin remains empty
and the operational recommendation is unchanged by this measurement.
