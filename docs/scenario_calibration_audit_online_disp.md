# Scenario calibration audit

- Contract: `scenario_calibration_audit_v1`
- Folds: 37; decision rule: frozen risk-neutral squad (scenarios never influence the decision)
- Anchor: form_window=6, bench_weight=0.0; 100 scenarios/fold
- Selection shift: online (mean -31.79 pts); double-gameweek scale 1.0
- Dispersion: online (mean scale 1.146, final online scale 1.155)

## Decision-level calibration

| Question | Scenario claim | Reality | Verdict basis |
| --- | ---: | ---: | --- |
| Realized below scenario q10% | 0.10 | 0.19 | calibrated if close |
| Mean PIT (uniform target 0.50) | 0.50 | 0.51 | bias if far from 0.5 |
| PIT < 0.10 rate | 0.10 | 0.16 | lower-tail honesty |
| PIT > 0.90 rate | 0.10 | 0.16 | upper-tail honesty |
| Bad week P(score < 40) | 0.26 | 0.14 | reliability |
| Scenario mean minus realized | 0.00 | +2.69 | location bias |

## Player-level interval coverage (nominal 90%)

| Position | Coverage |
| --- | ---: |
| DEF | 0.785 |
| FWD | 0.852 |
| GK | 0.873 |
| MID | 0.783 |

Measurement only: nothing was repaired, reweighted, promoted, or read from
the locked holdout.
