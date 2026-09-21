# Football candidate development results — 21 September 2026

These are reused-development measurements. They validate the implementation and distinguish useful from unsuccessful extensions; they are not independent live-model promotion evidence.

## Equal solver accuracy

Both frozen arms were re-solved on every one of 56 gameweeks (2024–25 and 2025–26, GW11–38). All 112 primary and secondary objectives were proved optimal with LP linearization level 2, one worker, seed 0 and the same deterministic budget. No player pruning or outcome-selected weeks. The earlier limited-proof attempt is retained separately.

The comparator is the previously registered historical component forecast from the production model family, not a replay of today’s live capture. No Top100 multiplier is applied. Its 204 missing point forecasts retain the existing ridge fallback; no players are removed from the decision universe. Each week independently selects a squad under a 100.0 budget; this is not the score of a season-long transfer strategy.

Team-share minus control: **4.9821 points/week**, descriptive 97.5% four-week block-bootstrap interval **[1.6158, 8.2857]** (5,000 replicates, seed 0). Season differences: **+2.4643**, **+7.5000**. This is weekly squad selection, not a measured long-run transfer policy.

Production prediction parity passed all 56 folds, maximum component/total discrepancy 7.11e-15. Six hard-case production optimizer calls matched complete research decisions. All 112 frozen decisions matched the production official autosub/captain scorer, including the preserved card-participation edge case.

## Fixed future-role ablation

Twelve origins: GW11/15/19/23/27/31 in each season, with one frozen history and roster for three future weeks. Both arms use the same final historical calendar and a proxy cutoff 90 minutes before the first kickoff. This is not verified historical deadline availability. An initial attempt correctly failed the strict future-fixture guard; the correction and all attempts were retained before future metrics were read.

Loss differences below are role-transition minus fixture v1, averaged over origin leads 2 and 3. Positive means worse. Descriptive 95% intervals resample origins within season (5,000, seed 0); these multiple exploratory metrics are not promotion tests.

| Metric | Difference | 95% interval |
| --- | ---: | --- |
| points_mse | +0.093001 | [+0.071324, +0.113669] |
| minutes_mae | +5.107374 | [+4.901834, +5.292799] |
| appearance_brier | +0.010942 | [+0.008665, +0.013164] |
| goals_mse | +0.000447 | [+0.000271, +0.000656] |
| assists_mse | +0.000140 | [+0.000018, +0.000254] |
| cs_brier | +0.000480 | [-0.000009, +0.001008] |
| dc_brier | +0.000632 | [+0.000155, +0.001275] |

**Decision: do not enable the stationary role transition by default.** It worsens points and minutes in both seasons. Keep the measured fixture v1 path as the candidate. Do not tune the transition prior against these same origins.

| Season | Lead | Arm | Point MSE | Minute MAE | Appearance Brier | Goal MSE | Assist MSE | CS Brier | DC Brier |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2024-25 | 1 | role | 3.438824 | 14.068512 | 0.091096 | 0.037918 | 0.036613 | 0.053801 | n/a |
| 2024-25 | 1 | v1 | 3.438824 | 14.068512 | 0.091096 | 0.037918 | 0.036613 | 0.053801 | n/a |
| 2024-25 | 2 | role | 3.889151 | 19.461409 | 0.119702 | 0.041403 | 0.038068 | 0.059154 | n/a |
| 2024-25 | 2 | v1 | 3.838103 | 15.735104 | 0.112032 | 0.041120 | 0.038038 | 0.058743 | n/a |
| 2024-25 | 3 | role | 4.236162 | 22.938920 | 0.139993 | 0.046336 | 0.037750 | 0.064239 | n/a |
| 2024-25 | 3 | v1 | 4.093216 | 16.460373 | 0.123135 | 0.045963 | 0.037444 | 0.063169 | n/a |
| 2025-26 | 1 | role | 3.686127 | 12.194636 | 0.079939 | 0.034236 | 0.029422 | 0.066477 | 0.044188 |
| 2025-26 | 1 | v1 | 3.686127 | 12.194636 | 0.079939 | 0.034236 | 0.029422 | 0.066477 | 0.044188 |
| 2025-26 | 2 | role | 4.126467 | 17.838576 | 0.105058 | 0.042251 | 0.038893 | 0.049823 | 0.043505 |
| 2025-26 | 2 | v1 | 4.086372 | 14.000535 | 0.099834 | 0.042041 | 0.038727 | 0.050198 | 0.042765 |
| 2025-26 | 3 | role | 4.050482 | 21.781313 | 0.128376 | 0.038366 | 0.031356 | 0.058896 | 0.042385 |
| 2025-26 | 3 | v1 | 3.912567 | 15.394708 | 0.114361 | 0.037444 | 0.031297 | 0.058080 | 0.041861 |

Each arm has 23 missing player-fixture labels across the registered origins/leads; they are counted and excluded from loss denominators, never treated as zero. Historical roster/calendar availability remains an unverified limitation. DEFCON is evaluated only in the scoring season with that target.

## Shared match worlds and clean sheets

Full-match clean-sheet replacement has worse Brier loss in both seasons: overall 0.0589216 → 0.0591519. Total point MSE changes only 3.6048366 → 3.6044295 on this event population. The CS change fails the head-specific acceptance criterion and does not replace the v1 mean. These event losses use a different population from weekly roster losses.

The simulator conserves match goal totals, assigns distinct scorers/assisters, respects zero-minute absence and shares the opposite score for CS. Four origins × 64 draws passed those structural audits. Its independent player minutes and full-match CS remain approximations; structural correctness is not calibration.

| Origin | Player-fixtures | Analytic mean | Simulated mean | Mean absolute difference |
| --- | ---: | ---: | ---: | ---: |
| 2024-25-gw11 | 678 | 1.249828 | 1.239358 | 0.146116 |
| 2024-25-gw15 | 630 | 1.200500 | 1.195904 | 0.138039 |
| 2024-25-gw19 | 709 | 1.182804 | 1.186710 | 0.130321 |
| 2024-25-gw23 | 736 | 1.148734 | 1.145342 | 0.137631 |

Audit correction: the first diagnostic subtraction had differently named player MultiIndex levels and cross-aligned rows. Corrected one-to-one key alignment produces the table above. Original diagnostic outputs and unchanged draws are preserved. No model refit or resampling was used for this correction.

## Planning and rival decision value

Synthetic tests verify a shared first action before information, different continuations after observation, legal hold, buy/sell and bank carry, and exactly four points of marginal free-transfer value in a hand-checkable hit-saving case. The new application and JSON-bundle CLI connect forecasts, complete 15-player planning and common-world official scoring. This is a bounded two-stage menu rollout, not a globally solved MDP.

Rival utility selects a menu member on the first half of common-world draws and evaluates that fixed member on the second half. It reports one-week win/tie probability separately from multiweek expected points. No authenticated Top100 cohort or historical ex-ante injury nodes were supplied, so no real-world recourse/rival uplift is claimed.

## Integration decision and next evidence

Integrate the opt-in candidate API/CLI, correct card participation and explicit solver setting with regression coverage. Keep the promoted live model unchanged. Reject automatic role/CS promotion. Before prospective model promotion: freeze the selected model/protocol, collect real pre-deadline roster/calendar inputs and settle later outcomes; compare calibration and official squad decisions on those untouched observations. For role improvement, model injury/selection states and elapsed fixture workload rather than repeatedly applying an unconditional position transition. Such a new candidate needs new locked evaluation, not tuning to this rejection.

Local raw artifacts, input/source hashes, per-fold decisions and failed attempts are retained with the task. An archive audit found a basename collision between prediction/football.py and scenarios/football.py: the original archive retained the scenario module only. A separate post-run manifest preserves their distinct relative paths before further edits; it is explicitly not backdated as a pre-run manifest. Full repository gates and delivery status are recorded separately after completion.

## Completed local verification

- Full Python gates: Ruff lint/format (812 files), strict mypy (323 source/operator files plus the new CLI), three import contracts, **6,564 passed / 14 opt-in or unavailable-engine skips**. Existing GP convergence warnings remain outside the candidate fit, which rejects nonconvergence.
- Web: generated schema unchanged, lint/format/types, **1,272 passed / 2 skipped**, production build, deployment asset checks and bundle budget; Playwright **88 passed / 2 skipped**, two workers. No owner-backend smoke flag was used locally.
- Real historical bundle E2E: 752-player 2025-26 GW11 roster, three weeks, 2,256 projections, proved optimal 15-player plan, 32 shared scenarios. Holdings and purchase book were constructed from the frozen comparator, not read from an owner. The reported 160.4249 expected net points is a forecast, not a measured realized gain.
- The first full Python attempt hit Windows path-length limits in 31 publication/handoff tests. A new short temporary directory passed the entire suite without changing their assertions. Failed attempts are preserved.

Remote CI and repository delivery are tracked in the associated pull request; these local checks do not claim a live model promotion.
