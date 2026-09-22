# Football components, Bayesian optimization and forward planning

Measured on 22 September 2026. This research implements a component ablation harness,
an optional BoTorch search backend, a causal standings alternative and a current-season
forward decision benchmark. It does not establish a replacement for the live model.
The preceding implementation is described in [the contextual model report](football_contextual_development.md).

## What changed

The sixteen factorial arms independently switch dynamic team goal intensity,
current-club goal/assist allocation, Gamma intensity uncertainty for clean sheets and
contextual defensive-contribution tails. Minutes and residual-point heads stay common.
Historical all-off and all-on endpoints reproduce frozen v1 and contextual v3.
Captured eligibility affects all forward arms once, before allocating goal/assist shares.
Existing production model identities and default strength parameters are unchanged.

The separate standings arm adds season-local points per game and goal difference per
match, for both teams, to a regularized Poisson team head (alpha 0.1). Five prior matches
shrink these features toward 1.35 PPG and zero goal difference. Only matches settled
strictly before each feature cutoff contribute. League position is not a motivation
bonus. A timestamp-unit mismatch was caught by the boundary test and fixed before the
experiment; comparisons explicitly use nanoseconds.

BoTorch 0.18.1 is an optional `research-bo` extra, not a required backend dependency.
`SingleTaskGP` and `LogExpectedImprovement` operate on normalized inputs using CPU double
precision. The minimized loss is sign-reversed and standardized. Fixed observation
noise is numerical regularization, not a claim that overlapping gameweeks are independent.
The implementation follows the [official BoTorch tutorial](https://botorch.org/docs/getting_started).

## Protocol and limits

- Inner validation: 2023-24 GW11, 15, 19, 23, 27, 31 and 35, equal-origin point MSE.
- Search knobs: team half-life 30–180 days, Gamma prior strength 4–24, current-club role
  prior 3–30 full matches. Search changes the attack-only arm; CS and DEFCON stay at v1.
- Each method gets 12 unique evaluations, including four identical starting points,
  from the same fixed 128-point scrambled Sobol pool. All three seeds are reported.
  The `random` label in raw evidence means Sobol sequence order, not IID random search.
  The other comparator follows the existing fixed-Matern sklearn GP/EI convention.
- All nine recommendations were frozen before outer evaluation. No outer-result tuning.
- Outer evaluation: 28 gameweeks each in 2024-25 and 2025-26, plus completed GW1–5 in
  2026-27. The older seasons were already development data, not pristine holdouts.
- Current-season evidence reconstructs a roster retrospectively from one official
  capture. It has 3,191 player-week rows, 1,532 appearances and no missing DEFCON counts.
  Current injuries, taker ranks, team strengths/FDR and analyst text are not backfilled
  into historical forecasts; ambiguous transferred identities are not invented.
- All 61 outer folds completed: 27 arms × 61 weeks × two strata = 3,294 loss records,
  with zero failed weeks. The appeared-player stratum is a diagnostic, not a deployable
  selection rule based on knowing who will play.
- Equal-gameweek means are used throughout. Exploratory paired intervals use circular
  four-week blocks, 2,000 resamples and seed 120. These are not multiple-testing-adjusted
  confirmatory intervals. Five dependent current weeks cannot support a promotion claim.
- Search shares memoized objective evaluations across methods. Total wall times therefore
  do not establish comparative algorithm speed; acquisition overhead and logical budgets
  are recorded separately. Restricting acquisition to the pool is not global optimization.

The first experimental run is invalid and preserved locally. It mistakenly included the
first archived season's zero-history rows in supervised fitting. The corrected run excludes
2022-23 from supervised training, while retaining raw history for priors, matching the
frozen comparator. The unchanged search protocol was rerun in full. A real-data preflight
matched reference MSE 3.504025709171694 before search. Across all 56 older outer weeks,
maximum endpoint point-MSE discrepancies were 8.9e-16 for v1 and zero for v3.

## Separate component results

Point MSE, lower is better. Single-component rows switch only that component on.

| Arm | 2024-25 | 2025-26 | 2026-27 GW1–5 |
|---|---:|---:|---:|
| Frozen v1 control | 3.638197 | 3.592529 | 4.993791 |
| Dynamic team intensity | 3.652116 | 3.592993 | 5.009442 |
| Current-club goal/assist allocation | 3.636594 | 3.592611 | 4.987102 |
| Uncertain CS intensity | 3.640323 | 3.595325 | 4.993164 |
| Contextual DEFCON | 3.638197 | 3.591230 | 4.982651 |
| All four / contextual v3 | 3.652257 | 3.597900 | 4.993401 |
| Standings head | 3.635079 | 3.588676 | 4.997246 |
| Frozen BoTorch attack candidate | 3.644184 | 3.591215 | 5.003656 |

DEFCON did not score points in the 2024-25 rules, so its identical point MSE that season
is not an improvement or a valid reward-model comparison for the new rule.

Current-season component losses expose cancellation hidden by total-point MSE:

| Arm | Goal MSE | Assist MSE | CS Brier | DEFCON Brier |
|---|---:|---:|---:|---:|
| Frozen v1 control | 0.044056 | 0.043665 | 0.084257 | 0.044980 |
| Current-club goal/assist allocation | 0.044105 | 0.043807 | 0.084257 | 0.044980 |
| Contextual DEFCON | 0.044056 | 0.043665 | 0.084257 | 0.045141 |
| All four / contextual v3 | 0.044238 | 0.044099 | 0.084242 | 0.045141 |
| Standings head | 0.044152 | 0.043770 | 0.084105 | 0.044980 |
| Frozen BoTorch attack candidate | 0.044384 | 0.044193 | 0.084257 | 0.044980 |

Current-club allocation slightly improves aggregate point MSE while worsening both goal
and assist MSE. Contextual DEFCON also lowers total-point error while worsening its own
event Brier score. These are not reliable component upgrades. The same warning survives
the appeared-player diagnostic: control point MSE 9.2660 versus contextual DEFCON 9.2440,
but DEFCON Brier rises from 0.08601 to 0.08696. BoTorch's appeared-player point MSE is 9.3011.

Metric choice also matters: the roles arm's current goal Poisson NLL falls slightly
(0.143291 to 0.143173), whereas assist NLL rises (0.146595 to 0.147306). Its worse goal
MSE therefore does not mean every goal-distribution diagnostic worsens. Both count
likelihoods are retained in the per-week evidence; the result still lacks consistent
cross-component and cross-season improvement.

The standings head gains about 0.09% and 0.11% in the two older seasons, but loses about
0.07% in the five current weeks. Its information may be useful, but this version has not
earned promotion. Dynamic goal-only team filtering similarly does not beat the existing
team head merely because it is Bayesian.

The full factorial analysis also measures interactions, not just one-switch comparisons.
For example, the 2025-26 main effect of uncertain CS raises point MSE by about 0.00270
(exploratory block interval 0.00112 to 0.00418). Increasing intensity variance raises
the Gamma-Poisson zero-goal probability; that mathematical property does not establish
better calibration. Current-season full-v3 MSE difference is -0.00039, with an exploratory
interval spanning approximately -0.02283 to +0.02205.

Position-specific diagnostics were generated for six arms and four positions across all
61 weeks (1,464 records). They remain diagnostic rather than a post-hoc rule to deploy
the best-looking position or seed. No component or position blend was selected on these
outer results.

For example, current DEFCON Brier improves for midfielders (0.03276 to 0.03222) but worsens
for defenders (0.07681 to 0.07797). The current-club allocation arm raises forward point MSE
from 4.54215 to 4.59122; forward goal and assist MSE also worsen. These are hypotheses for
position/exposure-specific calibration, not sufficient evidence to select a position blend.

Minutes and appearance heads are shared across arms and their losses are also recorded.
The control's current-season minutes MAE is 16.67754 and appearance Brier is 0.14108.
Mean appearance probability 0.47745 is close to the observed rate 0.48114, but aggregate
calibration does not imply accurate player-level minutes. Contemporary playing percentages
do not identify starting, substitution or multiweek recovery transitions. Historical LLM
news effects cannot be claimed without timestamped source evidence at those past decisions.

## BoTorch comparison

Inner validation point MSE; lower is better. Equal evaluation counts and common initial
designs are used, but GP kernel fitting conventions differ, so this benchmarks the actual
implementations rather than isolating only acquisition-function choice.

| Search | Seed 0 | Seed 1 | Seed 2 |
|---|---:|---:|---:|
| Sobol sequence | 3.69101324 | 3.69153088 | 3.69103538 |
| sklearn GP / EI | 3.69082288 | 3.69089266 | 3.69082149 |
| BoTorch GP / LogEI | 3.69082288 | 3.69089266 | 3.69079390 |

The untuned attack arm scores 3.69285242; frozen v1 scores 3.71553964 and full contextual
v3 scores 3.68351728 on those inner origins. BoTorch improves the attack-only starting
point very slightly and matches sklearn's selected winner for two seeds. It does not
demonstrate a meaningful independent advantage at this budget.

Across the 24 post-initial acquisition calls, BoTorch uses 3.233 seconds in total
(median 0.0428 seconds), versus sklearn's 0.0265 seconds (median 0.00111 seconds).
This records search overhead only, including the first optional import; shared objective
memoization prevents an honest comparison from simply ranking whole-run wall times.

The pre-nominated seed-0 BoTorch candidate uses a 106.97884-day half-life, team prior
18.36625 and role prior 4.48444. Against v1 its outer point MSE changes by approximately
+0.165%, -0.037% and +0.198% respectively. Positive means worse. Its current-season
paired MSE difference is +0.00986, with exploratory interval -0.00431 to +0.02404.
There is no consistent model-promotion case. Searching longer on these same evaluation
weeks would increase selection bias rather than create independent evidence.

## Current-season forward decisions

The official 22 September capture supplies 667 players, current eligibility/prices and the
GW6–10 calendar. A 100.0-budget squad is constructed from control GW6 forecasts; it is not
the owner's squad. Both arms use the same 15-player starting purchase book, one free
transfer, identical bank, no chip rights and four-point hits. Eligibility is held fixed
until a new observation; a learned recovery/rotation process is not supplied.

For each arm and 3/5-week window, compare holding all 15, deterministic transfer planning
and observed two-stage recourse. The highest-projected held player's future expected points
receive symmetric +/-30% updates, each probability 0.5. These are hand-authored information
stress cases, not calibrated injury probabilities or sampled realized match outcomes.
Only continuations see the observation. The mean forecast is unchanged. Extra free-transfer
value is measured with paired continuation solves. Per-solve wall/deterministic budgets
are 120/60 seconds; recourse requires proved optimal subproblems.

This is a restricted first-action menu and one future information stage, not a complete
belief-state MDP. Cross-model projected point totals cannot establish predictive accuracy;
future actual outcomes do not yet exist. A positive information-sensitivity value is not
measured prospective policy profit.

| Model | Weeks | Method | Expected net points | Solver status |
|---|---:|---|---:|---|
| control | 3 | hold | 162.933 | OPTIMAL |
| control | 3 | deterministic | 165.837 | OPTIMAL |
| control | 3 | recourse | 167.860 | OPTIMAL_RESTRICTED_MENU |
| control | 5 | hold | 273.903 | OPTIMAL |
| control | 5 | deterministic | 248.401 | FEASIBLE |
| control | 5 | recourse | Unverified | FAILED |
| botorch | 3 | hold | 163.714 | OPTIMAL |
| botorch | 3 | deterministic | 166.284 | OPTIMAL |
| botorch | 3 | recourse | 168.157 | OPTIMAL_RESTRICTED_MENU |
| botorch | 5 | hold | 273.488 | OPTIMAL |
| botorch | 5 | deterministic | 272.787 | FEASIBLE |
| botorch | 5 | recourse | Unverified | FAILED |

The 5-week control deterministic incumbent is worse than the hold alternative (248.401
versus 273.903) and spends 28 hit points. Its deterministic budget expired; the 33.593-point
optimality gap prevents treating it as an optimal recommendation. The preserved failure
is a solver-quality finding, not evidence that transfers are intrinsically harmful.
The research comparison must prefer the feasible hold alternative when interpreting that
case. A production follow-up should ensure a known feasible hold plan seeds or bounds the
search and remains available under timeout. This study does not silently replace the
unproved result, expand solver budgets or claim an MDP win from failed comparisons.

All 12 scheduled cases were attempted. Eight are optimal or optimal within the restricted
action menu; two 5-week deterministic results are unproved incumbents and both 5-week
recourse comparisons reject unproved subproblems. Even the BoTorch 5-week incumbent is
below its own hold alternative (272.787 versus 273.488).

For the 3-week control, deterministic planning improves the hold score by 2.904 projected
points; observation-contingent recourse adds 2.023 under the specified stress nodes.
The corresponding BoTorch figures are 2.570 and 1.873. Both models hold transfers in the
first week. The paired marginal value of one additional free transfer in the continuation
is 0.667/0.801 points in the control's low/high nodes, and 0.800/0.630 for BoTorch. These
are conditional diagnostics, not a universal transfer value to hard-code into the MDP.
The low/high continuations change both transfers and captain choices: both models sell
the perturbed player in the low node and retain him in the high node. The sensitivity
gain is therefore not isolated evidence of a transfer-only or captain-only improvement.

## Research interpretation and next work

[Official FPL experts](https://www.premierleague.com/en/news/4322002) emphasize secure
minutes, patience over multiple weeks, banked transfers and justified hit costs. Here those
ideas map to measurable inputs, constraints and hold/recourse alternatives; advice is not
converted into arbitrary player multipliers. Timestamped manager evidence belongs in the
existing source-resolution path, not retrospective training labels.

1. **Calibrate component targets first.** Measure goal/assist count likelihoods, CS event
   calibration and DEFCON threshold tails by position and exposure. Total-point gains
   caused by compensating component errors should not trigger promotion. Learn any blend
   on training seasons only, then freeze it before genuinely new weekly outcomes.
2. **Improve team-strength pooling.** Compare recent xG and schedule-adjusted attack/defence
   to the current goal-only filter. The adaptive period pooling described by
   [Macri-Demartino, Egidi and Torelli](https://arxiv.org/abs/2508.05891), with a 2026 JRSSC
   publication reference, motivates testing change-aware shrinkage instead of one fixed
   half-life. The current Gamma working filter is not an implementation of their full
   model. [Baio and Blangiardo](https://discovery.ucl.ac.uk/id/eprint/16040/) discuss
   overshrinkage, relevant to elite and newly promoted clubs.
3. **Use position-specific model alternatives with a clean holdout.**
   [OpenFPL](https://arxiv.org/abs/2508.09992) offers a public FPL/Understat ensemble and
   prospective 1–3-week evaluation reference. Its reported results are external, not
   reproduced here and not evidence of our system's superiority.
4. **Make planning quality robust before enlarging the MDP.** Preserve hold/control
   feasibility under timeout. Then estimate observation transitions from timestamped
   forecast, lineup and injury changes. Fit terminal bank/FT/chip value on training
   seasons only. Compare policies on identical forecasts and starting rights, including
   realized captain, transfer, autosub and hit outcomes.
5. **Use BoTorch as a research tool, not a guarantee.** Keep equal-budget baselines and
   frozen outer weeks. Only add parameters tied to interpretable football mechanisms;
   evaluate whether acquisition overhead buys a reproducible improvement. The present
   three-parameter result does not justify changing live forecasts.

An inference from these component trade-offs is to predeclare count-loss/calibration
constraints alongside the point objective in the next search. BoTorch supports
[constrained multi-objective optimization](https://botorch.org/docs/tutorials/constrained_multi_objective_bo)
and [log hypervolume acquisitions](https://botorch.org/docs/multi_objective).
Use deterministic qLogEHVI or an appropriate constrained single-objective formulation
when the objective is deterministic; qLogNEHVI becomes relevant with genuinely noisy
objective estimates. Overlapping validation weeks are not automatically independent
observation noise. This is a proposed experiment, not an implemented or measured win;
the current frozen search was not retuned after inspecting outer outcomes.

## Reproduction and evidence

Optional research setup: `python -m pip install -c constraints.txt -e ".[dev,research-bo]"` in a separate
Python 3.13 environment. The measured installation used BoTorch 0.18.1, GPyTorch 1.15.2 and PyTorch
2.6.0 (CPU double precision). The normal runtime does not require this extra.

```powershell
python scripts/measure_football_components.py --archive <archive> --training <causal-training.csv> --snapshots <capture-root> --snapshot-id <captured-id> --reference-losses <prior-losses.csv> --output <fresh-component-directory>
python scripts/analyze_football_components.py --losses <component-directory>/component-losses.csv --output <fresh-analysis.json>
python scripts/measure_football_planning.py --archive <archive> --training <causal-training.csv> --snapshots <capture-root> --snapshot-id <same-captured-id> --study <component-directory> --output <fresh-forward-directory>
```

The capture identity is `fpl-live-20260922T110843Z-4b6ef29af6cd`, captured at
2026-09-22T11:08:43.344068Z. Training SHA-256:
`50dc337e1a378525be0660e2754a3dda1b8324a36c4fccdea8cc47a16724ded3`.
Evidence contains source/archive hashes, frozen recommendations, all search trials,
per-week/stratum losses, factorial effects/interactions, position diagnostics and forward
solver status/gaps. Only locally generated trusted caches are read for diagnostics;
never load external pickle files. New output directories are required, preserving failures.

Raw captures, machine paths and local diagnostic logs are not part of the public report.
Local evidence directories: `.codex-tmp/football-components-study02` and
`.codex-tmp/football-forward-study02`. The invalid `study01` is retained and excluded.

## Local engineering validation

- Ruff and format checks pass for 840 Python files; strict mypy passes for 338 source/operator
  files and the three existing typed football CLIs; all three import contracts pass.
- Final complete Python suite: 6,697 passed, 15 skipped, nine existing GP convergence
  warnings. Skips cover opt-in integrations, missing Parquet support and the optional
  BoTorch test in the normal environment. The first full run caught a missing central
  BoTorch version pin; it was corrected and the complete suite rerun successfully.
- The isolated research environment separately passes all nine component/search tests,
  including a real BoTorch GP fit and acquisition call. Its inherited optional numexpr
  version warning and GPyTorch numerical-noise floor warning are recorded in local logs.
- Web schema generation, lint, format, type checks, build, deployment asset checks and size
  checks pass. Web unit tests: 1,282 passed, two skipped. Playwright: 88 passed, two skipped,
  two workers. These are isolated engineering/E2E checks, not live-backend or model-uplift proof.
- The reusable aggregate analyzer reproduces all previously reported means, paired
  intervals, main effects and interactions exactly, and also reports the appeared stratum.

After these gates, only report text was completed. No executable behavior was changed.
