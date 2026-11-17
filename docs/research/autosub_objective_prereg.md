# Picking the squad by its expected official score: protocol

Written before any solve on a real week, the pilot included, and not changed by a result. The
study was fixed after the paper's results were known; its series are supplementary to the
paper's and change none of its readings. Issue #1393 asked for it, and the parts it marks fixed
are copied here unchanged. Any later change goes into the dated "Deviations" section at the end,
with its reason, before the stage it affects runs.

## The question

The weekly program the paper uses maximizes a surrogate: the starters' expected points, the
captain's once more, and the bench's at a weight of 0.1, with bench order and vice-captain set
after the solve. The squads are then scored under the official rules, which the surrogate does
not price: a bench player counts only when a starter does not play and the formation allows him
in, in bench order, and the captain's bonus passes to the vice-captain only when the captain does
not play. Two questions:

1. Does a program that maximizes the expected official score pick squads that score more under
   the official rules than the surrogate's squads, for the same forecast?
2. Does the paired difference between the boosted and the linear model change when both pick by
   the expected official score?

## Code base

- Branched from `develop` at `99e07dad` on 16 November 2026.
- The scorer (`score_frozen_squad_decision`), the samplers (`scenarios/components.py`), the
  statistics module, `contracts/players.py` and `optimization/coefficients.py` are the ones the
  paper's runs used. If a pull request changes any of them before the run, the run waits for the
  owner.
- The bundle's driver modules (`drv_model.py`, `drv_ladder.py`, `drv_scorer.py`) are imported
  from `--driver <dir>` and never enter the repository; no unit test imports them.

## Arms, weeks and objectives (fixed)

- Arms `linear` and `boosted`, each with its forecast table and instance file from the bundle.
  `ridge` is left out: it has no appearance probability, conditional minutes or conditional
  points, so the foundation sampler cannot draw for it.
- The 147 decision weeks of 2021-22 to 2024-25 in the instance files. Never 2025-26 or 2026-27;
  the runner refuses any later row.
- Objectives per arm and week: `surrogate` (the proven decision in `decisions_proven.csv`, taken
  as it is), `autosub` (the expected official score), `scenario_mean` (the surrogate program
  with each player's value replaced by his mean over the optimization draw, through the bundle's
  driver at its defaults) and `surrogate_relineup` (the surrogate's squad with eleven, captain,
  vice-captain and bench order chosen by the expected official score, exact by formulation B's
  inner step), reported as a secondary comparison.

## Scenarios and seeds (fixed)

- The foundation sampler, `sample_component_scenarios` with `conditional_residuals`,
  `team_match_block` and `team_match_joint` left as `None`; residual history from
  `paired_conditional_residuals(rows_before, target=..., min_history_folds=8)`, the expanding
  window across seasons.
- Inputs as `_selected_component_inputs` builds them, with the week's whole pool minus fallback
  rows in ascending `player_id`, projections through `prepare_optimizer_projection` and the
  provenance the issue names, both digests recorded.
- One optimization draw per arm (label `autosub|saa|<arm>`) and one evaluation draw of 10,000
  scenarios (label `autosub|eval|<arm>`). A label's seed is
  `int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:16], 16)`, passed as
  `ScenarioConfig(scenario_count=S, deterministic_seed=seed)`. The pilot weeks use
  `numpy.random.Generator(numpy.random.PCG64(seed))` from the label `autosub|pilot_weeks`.
- **Burn-in.** A week where `paired_conditional_residuals` refuses for too little history is
  `burn_in` for both arms if it is for either; every objective takes the surrogate's decision
  there and the paired differences with `surrogate` are 0. The list is compared with
  `HISTORY_BURN_IN_FOLDS` (2021-22 gameweeks 2 to 10) and reported; a difference stops the run
  for the owner.
- **Fallback rows.** `is_fallback = 1` and `composition_route = direct_control` must mark the same
  rows. They are left out of the sampler's inputs and added after the draw: a fallback player
  with `fixture_count` 0 never appears; any other appears in every scenario and scores his
  instance `yhat_milli`. Selected fallback rows are counted per week and objective.

## The formulation

- **Formulation A**, sample average approximation in CP-SAT, as the issue writes it: the
  surrogate's constraints unchanged, a vice-captain and an ordered outfield bench, and per
  scenario the goalkeeper swap, the bench walk by count-only admission stated as an equivalence,
  and the vice-captain's bonus, maximized in integer milli-points.
- The count-only admission rule is used only if validation item 2 finds zero differences from
  the scorer's walk over every case it enumerates, across all eight legal formations (5-2-3
  included); otherwise the model encodes the scorer's walk.
- The model also carries inequalities every integer solution already satisfies (each of g, r and
  u at most its positive part and zero when its condition is false, and a slot coming on only
  while a place is empty). They change no decision and no value; they shorten proofs.
- **Bound.** Every week reports an upper bound on the in-sample optimum from the relaxation the
  issue describes (bench, captain and goalkeeper terms by their positive parts), solved with
  CP-SAT. On a full pool the captain and vice-captain pair variables number about 275,000, so
  each captain is paired with the best vice-captain term in the whole pool instead; that is still
  a valid upper bound, looser than the paired one. `bound_int` is the smaller of it and the
  solver's own bound; a solve or relaxation that ends without a proven bound gives none.
- **Hint.** The higher in sample of the surrogate's decision of the same arm and week and
  formulation B's incumbent, complete in every variable.
- **The week's decision** is the best by in-sample objective of the solver's incumbent (unless
  the wall clock stopped the search), the surrogate's decision and B's incumbent; a week whose
  own incumbent was below the hint is flagged `hint_better`.
- **Canonical lineup.** Squad and eleven kept; the six outfield bench orders and every
  vice-captain enumerated; ties broken by descending `expected_points`, then the lower code.
- **Formulation B** (the warm start, and the run's method only if the pilot rule says so): the
  exact inner step by enumeration with decomposition, and an outer neighbourhood search from the
  surrogate's squad: all one-player swaps, and two-player swaps within candidate lists of the top
  L = 12 players of each position by mean scenario points, fixed before any solve; within budget,
  quotas and club cap; first improvement; visiting order by `stable_rank`. It stops when no
  improving swap is left or after 200,000 evaluated squads, never on time.

## The scenario count S and the limits

- **Pilot:** 3 non-burn-in weeks per season, 12 in all, chosen by the generator above with
  `choice(sorted gameweeks, size=3, replace=False)` per season in ascending order; both arms use
  the same weeks. It reads no realized outcome.
- For each S in {100, 250, 500, 1000}, both arms are solved with three optimization draws
  (labels `autosub|pilot|<arm>|S<S>|rep<r>`, r = 0, 1, 2) and evaluated on one evaluation draw
  of 10,000 scenarios.
- **Rule:** the smallest S where (i) the mean over pilot weeks, arms and draws of eval(S) minus
  eval(S = 1000) is at least -0.02 points, paired on the common evaluation draw, with its
  standard error reported, and (ii) in each arm and draw at least 10 of the 12 pilot weeks are
  proven within the week's limit. If no S meets (ii), (i) is redone with formulation B and the
  run uses B.
- **Solver:** OR-Tools 9.15.6755 via `configure_solver`, one search worker, `random_seed = 0`,
  `linearization_level = 2` (on small enumerable pools it proved optima about ten times sooner
  than the default), `max_deterministic_time` = 300 per week-arm solve, `max_time_in_seconds` = 3,600 as a safety
  stop only. A solve that ends `FEASIBLE` or `UNKNOWN` with less deterministic work used than its
  limit counts as stopped by the wall clock; its incumbent is not taken and the week is listed.
  An unproven week keeps its incumbent with its bound and gap, and is never re-solved after a
  result is seen.
- If one full run would take more than 48 hours by the pilot's estimate, the estimate is posted
  on #1393 and the run waits for the owner.

## Stages

1. Stage 1 writes all decisions and their digests. Before anything reads a target week's rows it
   drops `appearance_target`, `start_target`, `minutes_target` and `points_target` of that week
   and every later week, and records that it did; a unit test checks that changing those columns
   leaves every stage 1 output byte-identical. Stage 1 never opens `tables/outcomes.csv.gz`.
2. Stage 2 scores every decision with `score_frozen_squad_decision` on the realized outcomes,
   under the official rule and the card rule. The surrogate's rows must first reproduce
   `realized_points` and `realized_points_card` on 147 of 147 weeks per arm.

## Comparisons and statistics (fixed)

Paired per-week differences of realized official points, in season and gameweek order, with
`season_aware_moving_block_interval` under `PromotionPolicy(confidence_level=0.90,
bootstrap_resamples=5000, moving_block_length=4, deterministic_seed=0)`, one identifier per
comparison as the issue lists them (`autosub|<comparison>|b4`, and `autosub|<comparison>_eligible|b4`
for the weeks with scenarios).

- **Primary readings, two, one per question:** `autosub|boosted_autosub_vs_surrogate_eligible|b4`,
  and the third series of `autosub|boosted_vs_linear|b4` (boosted minus linear under `autosub`,
  minus the same under `surrogate`), on all 147 weeks.
- Every other interval, the card rule, the secondary populations and `surrogate_relineup` are
  reported beside them and change no reading.
- **Reading:** above 0 when the lower end is greater than 0, below 0 when the upper end is less
  than 0, otherwise no difference. Nothing is claimed beyond the intervals.

## What the report contains

The seven headings of the issue: design (this note's merge commit, the formulation, S and the
pilot, the limits, the burn-in weeks, deviations), validation results, compute, results per arm,
paired comparisons with the two primary readings first, what changes for the paper's question,
and limitations (the foundation sampler's assumptions and calibration standing, the fallback
rule, burn-in weeks, unproven weeks, the approximation's optimism measured as in-sample minus
out-of-sample, and that the study was fixed after the paper's results were known). The two runs'
output digests are posted on #1393; the data bundle, the driver and the results are never
committed.

## Deviations

None yet.
