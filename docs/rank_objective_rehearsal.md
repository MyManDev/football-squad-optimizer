# Rank-probability objective rehearsal (template rival)

- Contract: `rank_objective_rehearsal_v1`; folds: 37; scenarios/fold: 100; anchor form_window=6, bench_weight=0.0
- Rival: the fold's own risk-neutral squad (template). Claimed = the optimizer's scenario probability of finishing ahead; realized = share of folds it actually did.

| Budget (xP) | Folds | Claimed P(ahead) | Realized ahead [90%] | Expected cost | Realized cost | Starters changed | Captain changed | Proven |
| ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 33 | 0.53 | 0.33 [0.22, 0.48] | -0.38 | +1.24 | 2.1 | 0.12 | 0.82 |
| 2 | 37 | 0.52 | 0.41 [0.28, 0.54] | +0.79 | +1.59 | 2.8 | 0.27 | 0.11 |
| 4 | 37 | 0.46 | 0.35 [0.24, 0.49] | +2.27 | +4.14 | 3.6 | 0.24 | 0.03 |
| none | 37 | 0.33 | 0.32 [0.21, 0.46] | +6.31 | +4.51 | 4.8 | 0.32 | 0.00 |

Residual input: `calendar_blind_baseline` (`1ed41f94f245b06d…`). Measurement only; the locked holdout was not read.
