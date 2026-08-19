# Rank-probability objective rehearsal (template rival)

- Contract: `rank_objective_rehearsal_v2`; folds: 37; scenarios/fold: 200; anchor form_window=6, bench_weight=0.0; claim scenarios: held_out_half
- Rival: the fold's own risk-neutral squad (template). Claimed = the optimizer's reported probability of finishing ahead (in-sample = on the scenarios it was chosen on); realized = share of folds it actually did; level = ended equal.

| Budget (xP) | Folds | Claimed P(ahead) | In-sample | Realized ahead [90%] | Level | Expected cost | Realized cost | Starters changed | Captain changed | Proven |
| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 37 | 0.40 | 0.51 | 0.30 [0.19, 0.43] | 0.14 | +0.80 | +2.92 | 1.7 | 0.14 | 0.84 |
| 2 | 37 | 0.44 | 0.55 | 0.32 [0.21, 0.46] | 0.03 | +1.06 | +3.76 | 1.9 | 0.22 | 0.08 |
| 4 | 37 | 0.45 | 0.53 | 0.30 [0.19, 0.43] | 0.11 | +0.99 | +2.78 | 1.8 | 0.22 | 0.00 |
| none | 37 | 0.45 | 0.53 | 0.35 [0.24, 0.49] | 0.16 | +0.95 | +1.51 | 1.7 | 0.22 | 0.00 |

Residual input: `calendar_blind_baseline` (`1ed41f94f245b06d…`). Measurement only; the locked holdout was not read.
