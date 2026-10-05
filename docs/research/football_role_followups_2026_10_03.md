# Two bounded role-model follow-ups

A retained-history indicator passes the prespecified development gates. A scalar-temperature candidate fails them. The accepted gain is small; neither run establishes calibrated probabilities, independent predictive superiority or live FPL gains, and neither activates a runtime change.

Both use the unchanged joint start/cameo model as the reference. The run commit is `64362f2c06a1957ebaa12128ce74cd9157e0227f`; measured source hashes match `49b451ae011eba21e59a0932e3deea9333a1ca7d`. There are 13 origins: GW11, 19, 27 and 35 of 2023-24 and 2024-25, plus settled GW1-5 of 2026-27. The historical readset contains 12 files from 2022-23, 2023-24 and 2024-25, with 2022-23 used for priors. No 2025-26 access is reported. Current evidence is capture `fpl-live-20261001T233218Z-7945d6b3c732`, captured at `2026-10-01T23:32:18.344567Z`.

Each candidate changes only the conditional start/cameo law, preserving appearance `q`, within-role minute laws and other fitted heads. Derived minutes and points can still change through the role mixture. Results use identical known-role populations and average origins equally. Negative differences are better.

| Candidate | Cohort | Role log-loss change | Role Brier change | Minutes MAE change | Points MAE change |
| --- | --- | ---: | ---: | ---: | ---: |
| Temperature | Historical | -0.000198 | -0.000129 | +0.073016 | -0.000555 |
| Temperature | Current | -0.001029 | +0.000275 | +0.295463 | -0.001069 |
| Temperature | Overall | -0.000518 | +0.000026 | +0.158573 | -0.000753 |
| Retained history | Historical | -0.000466 | -0.000081 | -0.061403 | -0.001648 |
| Retained history | Current | -0.001906 | -0.000432 | -0.071685 | -0.004868 |
| Retained history | Overall | -0.001020 | -0.000216 | -0.065358 | -0.002886 |

Temperature estimates one scalar per origin from the final four settled causal training groups, using an earlier-prefix role head. It transfers that scalar to the full outer head, an explicit modeling assumption. Its fixed range is [1, 2]: four origins choose T=1, nine choose interior values, and the maximum is 1.323284. It fails four of 50 recorded checks: historical and current minutes MAE, and current and overall role Brier. The log-loss improvement does not override those failures. No further temperature search was run.

The other candidate appends only `has_retained_player_history = (past_rows > 0)` to the role head, retaining the existing estimator settings. This means retained causal fixture rows, not a complete playing career. All 35 numerical gates pass. Current points MAE falls from 1.266420 to 1.261552; minutes MAE from 16.930400 to 16.858715; overall role log loss from 0.564326 to 0.563307. The largest position-level deterioration is historical goalkeeper role log loss, 0.399%, within the declared 1% tolerance.

Acceptance is by cohort, not every origin. Current GW1 role log loss worsens from 1.584764 to 1.588358, Brier from 0.760487 to 0.762084, and minutes MAE from 28.959372 to 29.004465. This result does not resolve or explain the original GW1 weakness. Training populations contain 3,011-24,180 known positive-role rows, including 82-282 without retained history; these overlapping counts are not distinct observations.

Independent receipt-only reconstruction checked all 65 origin/position cells per candidate and reproduced every gate decision. Paired populations and appearance scores match. All five preserved baseline score, comparison and diagnostic files match the original measurement byte for byte; raw old prediction matrices were not retained.

Each run completes 13 outer fits plus 13 additional small role-head fits, without retries. Total elapsed time is 109.057 seconds for temperature and 107.204 for retained history, including preparation of 49.841 and 52.430 seconds respectively. The retained receipt's 13 estimator fits are those same 13 role-head fits, not another group.

The retained indicator warrants a separate implementation review. This development result is not deployment approval or a significance test. Shared appearance errors, reconstructed populations, capture-time roster omissions, overlapping origins and residual point assumptions remain. Causal cutoffs do not prove historical deadline availability. The [compact evidence record](football_role_followups_2026_10_03.json) preserves exact receipt hashes, support counts and both outcomes. Preparing it used only generated artifacts, with no new fit, solver, test, provider call or raw input-data read.
