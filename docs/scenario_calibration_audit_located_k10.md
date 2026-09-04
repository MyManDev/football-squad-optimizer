# Scenario calibration audit

- Contract: `scenario_calibration_audit_v1`
- Folds: 37; decision rule: frozen risk-neutral squad (scenarios never influence the decision)
- Anchor: form_window=6, bench_weight=0.0; 100 scenarios/fold

## Decision-level calibration

| Question | Scenario claim | Reality | Verdict basis |
| --- | ---: | ---: | --- |
| Realized below scenario q10% | 0.10 | 0.84 | calibrated if close |
| Mean PIT (uniform target 0.50) | 0.50 | 0.06 | bias if far from 0.5 |
| PIT < 0.10 rate | 0.10 | 0.78 | lower-tail honesty |
| PIT > 0.90 rate | 0.10 | 0.00 | upper-tail honesty |
| Bad week P(score < 40) | 0.00 | 0.14 | reliability |
| Scenario mean minus realized | 0.00 | +35.77 | location bias |

## Player-level interval coverage (nominal 90%)

| Position | Coverage |
| --- | ---: |
| DEF | 0.772 |
| FWD | 0.850 |
| GK | 0.872 |
| MID | 0.772 |

Measurement only: nothing was repaired, reweighted, promoted, or read from
the locked holdout.
