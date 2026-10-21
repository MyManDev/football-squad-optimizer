# Retained-history support: one research-only role candidate

Status: the retained-history research measurement remains unexecuted. The parent run completed 30 combined synthetic tests for the retained-history and temperature drafts in 2.52 seconds. No actual input-data read, measurement fit or promotion is established by those synthetic tests. A real measurement still needs a separately coordinated slot.

The hypothesis is only a missing-versus-present discontinuity. Existing continuous `past_rows` already measures history quantity. Append `has_retained_player_history = (past_rows > 0)` to the two-class conditional start/cameo head, with no threshold, window, interaction or hyperparameter search. A retained older-season row counts even when `season_rows == 0`. A retained current-season nonappearance also counts. Missing retained history is not proof of missing career experience, injury, poor fitness, or a cause of the observed GW1 losses.

Use the existing `StandardScaler` and `LogisticRegression(C=1, max_iter=1000, random_state=0)`, existing known positive-minute binary-label training population, exact one-class fallback and unsupported-role fallback. Shared `FEATURES`, the four-bin appearance head q, within-role minute heads, minute representatives, all other fitted heads and v1 remain unchanged. Each candidate is a deep copy of its own base fit; neither candidate experiment can mutate or share fitted state with the other. Native scoring recomputes changed minute exposure and teammate goal/assist shares. q, zero mass and eligibility must be elementwise identical. No new probability calibration claim follows from adding an indicator.

## Fixed measurement and budget

Use the exact clean source commit and immutable readset recorded in the sibling preregistration JSON: the same 12 files across retained 2022-23, 2023-24 and 2024-25, and the same captured 2026-27 GW1-5 payload identity as measurement02. The excluded season is denied before archive access or enumeration. No new source capture, network request, holdout read, live store, provider call or production artifact is allowed.

The original runner supplies exactly eight historical and five current origins. One base joint fit per origin produces both original joint and v1 forecasts. The additional head uses the exact causal supervised train, never target/future labels. Maximum 13 outer fits plus 13 role-head construction attempts; actual logistic fits can be fewer with a constant or unsupported population. Log attempts before fitting, including fixed fold, support counts, times and failure. Stop fitting subsequent origins after any failed fold; preserve partial evidence and do not retry or broaden the experiment.

The original runner still receives the base forecast. Require byte equality of measurement02 `scores.json`, `comparison.json`, `role-scores.json`, `role-comparison.json` and `role-diagnostics.json`. Old raw prediction matrices were not saved, so their historical byte equality cannot be claimed. During this run require a repeated base prediction to be exactly unchanged after candidate scoring. The candidate has its own arm and separately named score, support, diagnostic, comparison and result files. Source, helper, synthetic-test, protocol and preregistration hashes are recorded before fit and checked afterward. Output directories are create-once; prior receipts are immutable.

## Predeclared acceptance

Require all 13 origins and all five position views, exact paired row/known/unknown/scored counts, and nonempty role-scoring populations. Do not discard unsupported folds or impute zero losses. Average paired losses by origin, never by pooled player count.

* ALL historical and current role NLL and Brier must each be nonworse; overall ALL role NLL must strictly improve.
* GK/DEF/MID/FWD role NLL and Brier must each be at most 1% worse in historical, current and overall views. A zero baseline permits only zero candidate loss.
* ALL historical and current point MAE and minute MAE must each be nonworse.
* Any missing required metric, failed fold, changed protected q/eligibility, baseline mismatch, changed code/readset or exceeded budget refuses acceptance. Report every metric and negative result; no alternative indicator is selected afterward.

Even acceptance is retrospective development evidence, not calibrated live probabilities, predictive superiority, realized gain or deployment authorization. Existing measurement limitations remain: reconstructed historical populations, three-hour settlement and 90-minute deadline proxies, incomplete captured-player history, fixed per-appearance residual, and no historical availability/news reconstruction.

## Synthetic checks

The sibling test file was included in the 30-test combined synthetic run and covers absent retained-player history; older retained history with no current-season rows; actual current nonappearance; target-outcome invariance and future-history refusal; unchanged existing feature columns; invalid counts; constant and unsupported role fallbacks; isolated candidate objects; exact q at 0, intermediate and 1; unchanged within-role heads/means; all-origin acceptance; missing metric/population refusal; and zero-baseline relative-loss handling. It creates no archive, provider or live inputs.

Relevant source boundaries: `src/squadopt/prediction/football_features.py`, `src/squadopt/prediction/football_minutes_role.py`, `src/squadopt/prediction/football.py`, `src/squadopt/application/football_live.py`, and `scripts/measure_football_role_minutes.py`. These tracked files remain unchanged.

## Source provenance update

Measured code and completed full-gate source: `49b451ae011eba21e59a0932e3deea9333a1ca7d`. The required clean execution head is now `64362f2c06a1957ebaa12128ce74cd9157e0227f`, which adds only the reviewed public report and compact evidence document. All six `study.SOURCE_FILES` SHA256 values were compared without imports or data access and remain identical to the saved measurement02 receipt. The local provenance-update record preserves before/after draft hashes. This documentation-only head change alters no algorithm, gate, readset or measured-code semantics.
