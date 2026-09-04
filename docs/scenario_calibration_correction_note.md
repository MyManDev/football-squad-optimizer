# Reading the corrected scenario calibration audit

Companion to `scenario_calibration_audit_{development,online,dev_dgw,online_dgw}.md`
(contract `scenario_calibration_audit_v1`, `scripts.run_scenario_audit` with
`--selection-shift` and `--double-gameweek-scale`), on the operational control's
residual export (`1ed41f94…`), 2024-25's 37 folds, 100 scenarios a fold, the frozen
risk-neutral squad per fold. It follows the audit that found the raw scenarios wrong
([scenario_calibration_audit.md](scenario_calibration_audit.md): mean PIT 0.07, +34.5
location bias) and the negative result on per-player location components
(`_located_k10/_k2`): the curse is selection-time, not player-persistent.

## What was added

- **A decision-level selection-optimism shift** (`ScenarioEvaluationConfig.
  location_shift_points`): the chosen squad's scenario scores are moved by the measured
  winner's curse — `selection_optimism_profile_v1` on the control: −2.951 a starter,
  −3.863 the captain, i.e. **−36.3 at squad level**. Two ways to set it: `development`
  (that fixed constant; note it was measured on 147 folds that include 2024-25, so this
  variant is partly in-sample) and `online` (minus the mean of scenario-mean-minus-
  realized over the folds *before* each fold, after five warm-up folds — leakage-safe,
  and what a live ledger will provide as the season goes).
- **A double-gameweek spread scale** (`ScenarioConfig.double_gameweek_scale`, calendar
  required): doubles' idiosyncratic draws widened by 1.45 (the fixture-group conformal
  radii ratio).
- **A rival comparison** (`compare_fixed_decisions`, `RivalSquad`): both squads scored
  in the same scenarios — shared players cancel — with P(ahead), its Wilson interval,
  and difference quantiles; the shift cancels in the difference and is not applied.
- **Sampling intervals** on scenario probabilities (Wilson, 90%): a "0.14" from 100
  scenarios is [0.09, 0.22]; the interval says how much is the scenario count.

The live risk layer applies the development shift by default
(`squadopt.live.risk.DEVELOPMENT_SELECTION_OPTIMISM`), reports the interval, accepts
the capture's calendar (`fixture_counts_by_player`) for the double scale and rival
squads for the comparison, and states which of these were applied as its limits.

## The numbers (2024-25 held out, 37 folds, nominal 0.90 / 0.10 / 0.50)

| Question | raw | development shift | online shift | dev + doubles ×1.45 |
| --- | ---: | ---: | ---: | ---: |
| Realized below scenario q10 (target 0.10) | 0.78 | 0.16 | 0.24 | 0.16 |
| Mean PIT (target 0.50) | 0.07 | 0.55 | 0.51 | 0.55 |
| PIT < 0.10 / > 0.90 (target 0.10 each) | 0.78 / 0.00 | 0.14 / 0.14 | 0.22 / 0.16 | 0.14 / 0.14 |
| Bad week P(score < 40): claimed vs real (0.14) | 0.00 | 0.21 | 0.24 | 0.22 |
| Scenario mean − realized | +34.5 | −1.8 | +2.7 | −1.9 |
| Mean shift applied | 0 | −36.3 | −31.8 | −36.3 |

Player-level 90% interval coverage is unchanged by any of it (DEF 0.79, MID 0.78, FWD
0.85, GK 0.87): the shift is decision-level and the double scale touches few 2024-25
rows.

## What it says

1. **The location is fixed.** −36 points at squad level moves mean PIT from 0.07 to
   0.51–0.55 and the bias from +34.5 to within ±3. The lower tail a live report prints
   is now roughly where it should be, where before it was fiction.
2. **The squad-level spread is now slightly too narrow, both ways**: 14% of realized
   scores fall below the scenario q10 and 14% above q90 (PIT sd 0.32 against the uniform
   0.29). The scenarios understate week-to-week squad variance by roughly a third — the
   common (gameweek-wide) component, or the covariance among selected starters, is
   underestimated. That is the next calibration item, and it is a dispersion question,
   not a location one.
3. **The online estimator works but is young**: 37 folds with 5 warm-ups leaves the
   early folds unshifted, which is why its lower tail reads 0.22. Over a season's ledger
   it converges to the same place; it is the honest live path (development constants
   until the ledger has enough settled weeks, then the ledger's own).
4. **Bad-week probability now over-claims** (0.21 vs 0.14 realized): with the location
   corrected, the too-wide-in-the-tail scenarios (item 2 is the opposite for the centre)
   are visible. Report it with its interval, not as a point.
5. **The double scale is right but invisible here**: 2024-25 has few doubles; the
   fixture-group measurement (0.85 → 0.90) is the evidence for it, not this audit.
6. **Player-level intervals still under-cover** (0.78–0.87 against 0.90) — the raw
   scenario spread per player is narrow; unchanged from the first audit and separate
   from everything above.

## What follows

- Squad-level dispersion: measure the common/team components against realized squad
  variance and scale them; re-audit (target: PIT tails at 0.10).
- Player-level spread: player-adaptive scales or the fixture-group radii into the
  idiosyncratic component.
- Ledger-driven shift for the live season: replace the development constants with the
  online estimate once enough settled gameweeks exist (a `season_ledger` reader is the
  natural place).
- Then the rank-probability objective (goal menus) on these scenarios.

## Follow-up (2026-08-18, later): squad-level dispersion

Artifacts: `scenario_calibration_audit_development_disp.{json,md}`,
`scenario_calibration_audit_online_disp.{json,md}` (audit contract unchanged; the
evaluation config gained `dispersion_scale`, applied around the raw scenario mean before
the shift, and the audit gained `--dispersion none|development|online`; online = the
root mean square of the earlier folds' location-corrected gaps in units of their own
scenario standard deviation, once the warm-up folds exist).

| Variant | Scale (mean / final online) | Realized < q10 | PIT < 0.10 | PIT > 0.90 |
| --- | ---: | ---: | ---: | ---: |
| development shift, raw spread | 1.000 | 0.16 | 0.14 (5/37) | 0.14 (5/37) |
| development shift, online dispersion | 1.146 / 1.155 | 0.14 | 0.14 (5/37) | 0.08 (3/37) |
| online shift, raw spread | 1.000 | 0.24 | 0.22 (8/37) | 0.16 (6/37) |
| online shift, online dispersion | 1.146 / 1.155 | 0.19 | 0.16 (6/37) | 0.16 (6/37) |

Reading, honestly:

- The spread **is** narrow, by about **15%** (the online scale settles at 1.15 and the
  development-constant estimate is the same number); widening by it moves every tail
  rate toward nominal or leaves it, and never away.
- The evidence is **thin**: at 37 folds one tail is five folds, and the 90% interval of
  5/37 is [0.07, 0.25] — it contains 0.10 before the correction as well as after. The
  online-shift variant's tail hits are concentrated in the warm-up folds (after them:
  3/32 and 1/32 low, 6/32 high).
- The **live default stays at 1.0**: a 15% widening on this evidence is a candidate,
  not a measured correction, and the live report now states the raw spread as a limit
  ("about 15% narrow, intervals including nominal"). `recommend_current_squad
  --risk-dispersion-scale` applies the candidate when asked and the report says so.
- What would settle it: more folds (a second season of the control export, or the
  ledger's own settled weeks) and the component-level measurement (common / team / player
  variances against realized) rather than one squad-level scale.
