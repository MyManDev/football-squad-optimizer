# Rank-probability objective rehearsal (template rival)

- Contract: `rank_objective_rehearsal_v2`; folds: 37; scenarios/fold: 100; anchor form_window=6, bench_weight=0.0; claim scenarios: held_out_half
- Rival: the fold's own risk-neutral squad (template). Claimed = the optimizer's reported probability of finishing ahead (in-sample = on the scenarios it was chosen on); realized = share of folds it actually did; level = ended equal.

| Budget (xP) | Folds | Claimed P(ahead) | In-sample | Realized ahead [90%] | Level | Expected cost | Realized cost | Starters changed | Captain changed | Proven |
| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 37 | 0.35 | 0.52 | 0.38 [0.26, 0.51] | 0.16 | +1.51 | +1.76 | 2.2 | 0.22 | 0.81 |
| 2 | 37 | 0.44 | 0.60 | 0.41 [0.28, 0.54] | 0.08 | +1.45 | +2.49 | 2.4 | 0.24 | 0.30 |
| 4 | 37 | 0.42 | 0.57 | 0.35 [0.24, 0.49] | 0.16 | +1.32 | +1.11 | 2.3 | 0.22 | 0.03 |
| none | 37 | 0.43 | 0.57 | 0.38 [0.26, 0.51] | 0.22 | +1.08 | +0.11 | 2.2 | 0.22 | 0.00 |

Residual input: `calendar_blind_baseline` (`1ed41f94f245b06d…`). Measurement only; the locked holdout was not read.
