# Sequential minute probabilities: development comparison

Measured on 28 September 2026. This changes only the minute head of the frozen
fixture football control. Three conditional logistic models estimate appearance,
60-minute eligibility given appearance, and full-match exposure given 60 minutes.
Their products form four nonnegative probabilities summing to one. Each scaler
fits only its eligible training rows. C=1 and seed=0 were fixed before measurement;
there was no parameter sweep. The copied control retains all other fitted heads
and minute-bin means; the output always names a separate development model.

The 33 paired folds are 2025-26 GW11-38 and 2026-27 GW1-5. Both periods have
already been used for development. Training uses strictly earlier whole gameweeks
and kickoff plus three hours before the cutoff. Three hours is an explicit
availability proxy, not a measured feed-delivery guarantee. Every control fold
reproduced its previous point MSE to 1e-10 before candidate interpretation.
No target outcomes are prediction features. No live producer or registry changed.

## Equal-week means, all positions

Lower is better for every loss below. These are paired descriptive measurements,
not a prospective significance or promotion claim.

| Season | Metric | Frozen control | Sequential minutes |
| --- | --- | --- | --- |
| 2025-26 | minute_nll | 0.568472 | 0.565359 |
| 2025-26 | minute_brier | 0.297413 | 0.296699 |
| 2025-26 | minutes_mae | 12.571179 | 12.606538 |
| 2025-26 | appearance_brier | 0.084670 | 0.084110 |
| 2025-26 | points_mse | 3.592529 | 3.582914 |
| 2025-26 | goals_poisson_nll | 0.108626 | 0.108201 |
| 2025-26 | assists_poisson_nll | 0.112617 | 0.112493 |
| 2025-26 | cs_brier | 0.057534 | 0.057557 |
| 2025-26 | dc_brier | 0.041583 | 0.041503 |
| 2026-27 | minute_nll | 0.853698 | 0.850096 |
| 2026-27 | minute_brier | 0.436707 | 0.436578 |
| 2026-27 | minutes_mae | 16.677543 | 16.697800 |
| 2026-27 | appearance_brier | 0.141079 | 0.139835 |
| 2026-27 | points_mse | 4.993791 | 4.985837 |
| 2026-27 | goals_poisson_nll | 0.143291 | 0.142917 |
| 2026-27 | assists_poisson_nll | 0.146595 | 0.146430 |
| 2026-27 | cs_brier | 0.084257 | 0.083991 |
| 2026-27 | dc_brier | 0.044980 | 0.045053 |

## Decision and failure modes

Do not promote this candidate. Minute log loss and Brier, appearance Brier and
total-point MSE improve slightly in both periods, but overall minute MAE worsens.
Goalkeeper minute MAE rises from 5.223 to 6.695 historically and from 7.722 to
9.373 in the five current-season weeks. Defender MAE also rises in both periods.
Forward and midfielder minute MAE improve, but selecting only those positions
after seeing these results would be a new, post hoc candidate, not this test.
Current-season DEFCON Brier worsens despite the small point-MSE improvement.

The next defensible development question is position-specific substitution and
starting-role persistence, with a newly declared model and evaluation. These
results do not justify changing the served football v1 or adding an arm to its
already frozen prospective protocol. The current research neither adds new
injury/news inputs nor demonstrates season-long transfer-policy value.

The JSON record includes all fold/position losses, the input and source hashes,
and the cutoff protocol. The runner is `scripts/measure_football_minutes.py`.
Missing goalkeeper DEFCON loss stays null, not zero. Future independent evidence
is still needed before claiming a live advantage.
