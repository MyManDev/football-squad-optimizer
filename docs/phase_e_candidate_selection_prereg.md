# Phase E Candidate Selection Preregistration

Status: frozen before any Phase E production code. This document authorizes no binding
measurement by itself. The E2 runtime probe and the E3 shadow evaluation each cite it, run
under the constants fixed here, and add their own artifact and `docs/measurements_index.md`
row. The E5 default decision is not decidable from this document and needs its own
preregistration.

## Question

For one gameweek, among the few legal squad decisions that are strongest under the Phase C
expected-points projection, does selecting by a fixed mean/CVaR utility over the shared Phase D
component scenarios choose a decision that is not worse than the deterministic Phase C control
in realized official points, with a bounded downside, and does the utility's ordering of
candidates carry any signal about realized outcomes?

## What Phase E is and is not

Phase E is a **candidate-based selector**, not a scenario-aware optimizer. The deterministic
CP-SAT model proposes; the Phase D scenarios and the official scorer dispose. Nothing is
re-optimized against scenario outcomes, and no player is removed from the pool before the
solver sees it.

The previous scenario-aware CP-SAT (`optimize_scenario_aware_squad`) is legacy. Its own
record closed the question: on the `risk_frontier` measurement every non-zero risk weight
lowered the mean and the floor together, and the scenario Bayesian optimization recommended
`risk_aversion=0`. It is not on the live path (verified 2026-09-04: `squadopt.live.risk`
imports `evaluate_fixed_decision` and `generate_scenarios` only), it is not a fallback for
Phase E, and it receives no new features. Its removal is scheduled after E5 behind a separate
audit that lists which recorded experiment artifacts become non-reproducible.

## Frozen inputs

| Input | Frozen value |
| --- | --- |
| Projection | Phase C: the in-season `projection_handoff_v1` for a live gameweek; the verified `phase_c_component_oof_v1` decision roster for historical folds |
| Deterministic optimizer | `OptimizationConfig()` defaults: `bench_weight=0.1`, `expected_points_scale=1000`, `solver_time_limit_seconds=10.0`, `deterministic_seed=0`, one search worker, the existing lexicographic tie-break |
| Scenario sampler | `sample_component_scenarios` with the `ScenarioConfig` defaults stated by `docs/phase_d_component_squad_calibration_prereg.md`: `scenario_count=1000`, `deterministic_seed=0`, `min_history_folds=8`, `min_player_observations=8`, `player_scale_shrinkage=10.0`, `player_location_shrinkage=None`, `double_gameweek_scale=1.0`; no shift, scale, recentering, winsorization, reweighting or bootstrap correction |
| Official scorer | `score_component_scenario_decision`, which completes bench order and vice-captain once with `complete_optimization_decision` (`optimizer_projection_order_v1`) and scores every scenario with `score_frozen_squad_decision` (`official_autosub_captain_v2`) |
| Integer scale | `scale_expected_points`: `round_half_up(Decimal(str(value)) * 1000)` |
| Risk weight ρ | 0.25 |
| Tail fraction α | 0.10 |
| Scenario count N | 1000, so the tail holds K_tail = ⌈αN⌉ = 100 scenarios |
| Weight scale W, risk weight R | W = 1000, R = ρW = 250 |
| Candidate counts probed in E2 | K ∈ {4, 8, 16} |
| Operational budget | 120 seconds of wall clock per decision, candidate generation plus scoring, on the machine named in the E2 artifact |

ρ, α, N and K are not searched inside Phase E. Searching them is Phase G's work and needs its
own preregistration.

## Candidate set

**Identity.** A complete decision is identified by its fifteen-player squad, starting eleven
and captain: `(squad, starting XI, captain)`. Squad and XI identities use sorted player ids.
Bench order and vice-captain are derived once by `optimizer_projection_order_v1` unchanged;
they are not additional search variables. Two decisions are the same candidate only when all
three signature fields match. A bench-player swap with the same XI and captain is a distinct
candidate because it can change official autosub points. Such candidates remain in the top-K
set even when their deterministic objectives tie; E2 measures the resulting diversity.

**Generation.** Candidate 0 is the control: the `optimize_squad` result, byte-identical to what
the live path publishes today, tie-break included. Candidate k is the solution of the same
model with one no-good constraint per earlier candidate j < k:

```text
sum(squad[i] for i in squad_j)
    + sum(starter[i] for i in eleven_j) + captain[captain_j] <= 26
```

A legal decision selects exactly 15 squad players, 11 starters and one captain. The sum is
27 exactly when all three signature fields match candidate j, so the constraint excludes that
complete decision and nothing else. Each candidate solve uses the control's own procedure:
primary solve, then the lexicographic tie-break with the primary's solution as a hint. The pool
is the complete validated projection pool; `required_player_ids` stays available as a constraint
seam and is not used by Phase E itself.

**Completeness.** Every candidate's primary status must be `OPTIMAL`. A candidate whose
primary status is `FEASIBLE` or `UNKNOWN` makes the set incomplete and Phase E falls back. A
model that becomes `INFEASIBLE` after j no-goods has exhausted the legal decision space; that
is a complete set of size j, not a failure. If the control itself cannot be solved, the
existing error behaviour is kept and Phase E produces no result at all.

**Bounded loss.** Because candidates are ordered by the deterministic objective, no candidate's
objective lies below the control's by more than δ_K, the gap of the K-th candidate. Whatever
Phase E selects therefore loses at most δ_K in that deterministic objective, including its
bench weight. For an exhausted set smaller than K, use the last available candidate's gap.
δ_K is recorded on every decision and its distribution is an E2 field. This is an objective
bound, not a guarantee about realized official points or downside outcomes.

**K.** E2 probes K ∈ {4, 8, 16}. The frozen K is the largest value for which, on every E2 pool:
(a) all candidates are `OPTIMAL`; (b) generation plus scoring stays inside the 120-second
budget; (c) two runs produce bit-for-bit identical candidate sets and selections. If K = 4 fails
any of the three, Phase E is not enabled and the E2 artifact says so.

## Common scenario scoring and coverage

Every candidate of one decision is scored on **one** `ComponentScenarioDraw` drawn over the
full projected pool. No candidate gets its own draw. The draw's `scenario_fingerprint` and
`component_fingerprint` travel into the Phase E result unchanged.

Coverage is decided by the scorer's own rule: a candidate with any squad player absent from
the draw's `scenario_points` is eliminated and counted. If the control is uncovered, or fewer
than two candidates are covered, Phase E is disabled for that decision with
`FALLBACK_SCENARIO_COVERAGE`. Absent players are never filled in.

## Utility and selection

For candidate d and scenario k let Y_{d,k} be the official-rules score from the scorer, and
y_{d,k} = `scale_expected_points(Y_{d,k}, 1000)` its integer form. The float utility is

```text
U(d) = (1 - ρ) · mean(Y_d) + ρ · CVaR_α(Y_d)
```

with CVaR_α the arithmetic mean of the K_tail smallest scores of that candidate. Selection
uses the equivalent integer

```text
U_int(d) = (W - R) · K_tail · sum_k y_{d,k} + R · N · sum_{k in tail(d)} y_{d,k}
```

which equals W · N · K_tail · U(d) up to the integer scale, so the ordering is exact and
reproducible. The arithmetic is Python integer arithmetic; no CP-SAT integer bound applies.

- **Selection rule.** The selected decision is the covered candidate with the largest U_int.
- **Ties.** Equal U_int is resolved toward the lower candidate rank; the control wins a tie.
- **Reported floats.** Mean is `sum_k y_{d,k} / (1000 * N)` and CVaR is
  `sum_{k in tail(d)} y_{d,k} / (1000 * K_tail)`, so both can be recomputed from the selection
  inputs.

The first engine uses the fixed seed, common random numbers and integer utility directly.
E2 records repeatability and seed sensitivity; E3 evaluates realized outcomes in shadow. A
per-decision separability test is deferred unless E2 demonstrates material Monte Carlo
instability and a later preregistration authorizes it.

## Calibration pin

Phase E may only act on a draw whose provenance is on a pin of calibrated model and sampler
versions. `PHASE_E_CALIBRATED_VERSIONS` in `squadopt.application.phase_e` stays empty until the
binding Phase D artifact records `verdict.status == "calibrated_internal"`. This is the
binding runner's actual success label; `failed` or `abstained` leaves the pin empty. The
application supplies the pin explicitly to the selector; the scenarios layer does not import
the application, and no live path is enabled by declaring the constant.

The pin matches `(draw.inputs.provenance.model_version, draw.inputs.contract_version)`, today
`("phase_c_control_components_v1", "component_scenario_foundation_v1")`. The prediction table
schema `component_prediction_v1` is not a model version and is not carried by the draw. The
draw's model, feature and target provenance must agree with its projection, and its sampler
config must match the frozen defaults. Seeds 0 to 4 are accepted only for the declared E2
sensitivity diagnostic; the binding run and eventual operational caller use seed 0. A missing
pin or mismatch yields `FALLBACK_PHASE_D_NOT_CALIBRATED`.

## Result contract

One frozen result per decision. Nothing in it is member-facing.

| Field | Meaning |
| --- | --- |
| `selected_result` | the `OptimizationResult` Phase E returns; equal to `control_result` on every fallback |
| `control_result` | candidate 0 |
| `selection_status` | one of the statuses below |
| `selected_candidate_rank` | 0 for the control |
| `candidate_count_requested` | the frozen K |
| `candidate_count_proven` | candidates with primary status `OPTIMAL` |
| `candidate_count_scored` | proven candidates covered by the draw |
| `scenario_fingerprint`, `component_fingerprint` | copied from the draw; `None` only when no draw was consulted |
| `utility_contract_version` | names this document's constants |
| `diagnostics` | the candidate table: rank, complete decision signature, objective, deterministic gap, squad and eleven overlap with the control, same captain, covered, mean, CVaR, and `U_int` |

Statuses:

- `SELECTED`: a covered candidate was chosen; rank 0 when the control itself wins.
- `FALLBACK_INCOMPLETE_CANDIDATES`: a candidate primary solve was `FEASIBLE` or `UNKNOWN`;
  `INFEASIBLE` after earlier candidates proves exhaustion, as specified above.
- `FALLBACK_SCENARIO_COVERAGE`: the control was uncovered or fewer than two candidates were.
- `FALLBACK_PHASE_D_NOT_CALIBRATED`: the draw's provenance is not on the pin.

There is no `INFEASIBLE` or `UNKNOWN` status: a control that cannot be solved raises exactly as
the live path raises today, and `used_fallback` is not a field because the status already says
it.

## E2: outcome-free runtime and coverage probe

E2 reads no realized outcome. Its pools are the three real 2026-27 decision points captured so
far (GW1 from the opening capture, GW2 and GW3 from their handoffs) and the 137-fold population
of the Phase D calibration for coverage. For each K in {4, 8, 16} it records:

- candidate generation time, per-candidate solver status and tie-break completion;
- the number of distinct complete signatures, squads, elevens and captains, the number of
  candidates differing from the control only in bench membership, and δ_K;
- the size of the candidates' player union relative to the pool;
- coverage: candidates eliminated and decisions with an uncovered control;
- scoring time per candidate and in total;
- bit-for-bit equality of candidate sets and selections across two runs;
- seed sensitivity: with the draw re-sampled under seeds 0 to 4, how often the selected rank
  changes, reported as a count and never used to pick a seed.

The frozen K follows the rule in the candidate section. The artifact names the machine and the
repository commit.

## E3: shadow evaluation

**Population.** The 137 folds fixed by `docs/phase_d_component_squad_calibration_prereg.md`,
ending at `2024-25-gw38`, with the same eligibility. The E3 runner requires the binding Phase D
verdict artifact to exist; a missing artifact stops the runner before evaluation. If that
verdict is `failed` or `abstained`, E3 still runs and writes its fields, but its verdict is
`technical_only` and no gate below binds anything.

**Per fold.** Generate the candidates from the fold's Phase C decision roster, draw the fold's
scenarios once, select, and score the control and every covered candidate against the fold's
realized points and minutes with `score_frozen_squad_decision`, the same realized scorer the
Phase D calibration uses. Let D_f be the realized score of the selected decision minus the
realized score of the control; D_f is exactly zero on a fallback fold and that zero is kept,
because it is what the operator would have experienced.

**Uncertainty.** Gate A reuses
`squadopt.experiments.statistics.season_aware_moving_block_interval` with
`PromotionPolicy(bootstrap_resamples=2000, moving_block_length=4, confidence_level=0.90,
deterministic_seed=0)` and the fixed `candidate_id="phase_e_vs_phase_c"`. Supply all 137
`(season, D_f)` pairs in season/gameweek order, including fallback zeros. The helper samples
overlapping blocks of four eligible folds within each season, truncating each resampled
season to its original length; blocks never cross seasons. Missing gameweeks remain absent,
as in the existing helper's eligible-fold contract. Its RNG is `random.Random`, seeded by 0
plus the integer represented by the first eight hexadecimal digits of SHA-256 of the
candidate id, not NumPy's RNG. The interval uses the helper's linearly interpolated 5th and
95th percentiles. Only the resampling fields of `PromotionPolicy` apply; Phase E's −1.0-point
threshold below remains its own gate.

Use the same season/block sampling policy and fixed seed for S, sampling fold indices with
all candidate rows of a sampled fold kept together, then recomputing Spearman correlation.
Candidate rows are never resampled independently. The disagreement-only mean is descriptive:
resample the full chronological fold population first and then retain disagreement folds in
each resample, without compressing the original time series before sampling. If an interval
cannot be computed (no disagreements or undefined correlations), report it as unavailable;
an unavailable S interval does not establish signal. No new resampling framework is required.

**Gates**, all fixed here:

- **A, harm excluded.** The 90% season-aware moving-block interval of mean(D_f) over all 137
  folds, under the uncertainty policy above, has a lower bound above −1.0 points per gameweek.
- **R, reliability.** The frozen K produces a complete candidate set on at least 95% of folds,
  no fold raises, and every non-selected fold carries a named status.
- **U, usefulness.** The selected complete `(squad, starting XI, captain)` signature differs
  from the control on at least 20% of folds, including bench-only changes.
- **S, signal.** Over every (fold, covered candidate other than the control) pair, the Spearman
  correlation between the predicted utility difference to the control, in points, and the
  realized paired difference to the control has a positive point estimate and a 90%
  season-aware moving-block interval that excludes zero, with fold candidate rows kept
  together as specified above.

**Reported, not gated:** mean(D_f) on all folds and on disagreement folds only, each with its
interval; season-level means; the mean of the worst 10% of folds by D_f; the realized lower
10% tail of the selected decisions against the control's across folds; counts of squad,
bench-only, eleven, captain and formation changes under the complete signature; status counts;
solve and scoring time.

**Verdicts, in order.** A Phase D verdict of `failed` or `abstained` gives `technical_only`.
With Phase D `calibrated_internal`, a failed A gives `harmful`; otherwise a failed R gives `technical_only`
with the reliability failure recorded; otherwise a failed U gives `inert`. Only a Phase D
`calibrated_internal` verdict with A, R and U all passing gives `shadow_eligible`. S is reported as
`signal: true` or `signal: false` and does not change the verdict.

`shadow_eligible` permits exactly one thing: E4, a shadow arm in the live decide phase that
computes the Phase E result and records it in the ledger diagnostics while the published
decision stays the control. Making Phase E the default is E5 and needs a new preregistration
that pools these 137 folds with settled prospective gameweeks.

## Power, stated before the run

Realized weekly points of regular starters in the four development seasons have a standard
deviation of 4.3 to 4.7, and the realized difference between two such starters in the same
gameweek has a standard deviation of about 6.2. Those are variance estimates only; no candidate
was evaluated to obtain them. Treating 137 folds as independent would give a standard error
of about 0.53 points and a 90% detection scale of roughly 0.87 points per gameweek. These are
only rough reference calculations: adjacent gameweeks are dependent, and the binding interval
uses the season-aware moving-block policy above. Complete-decision objective gaps are measured
by E2; no gap from an XI/captain-only probe is assumed for this candidate set. Superiority is
not a gate. Gate S uses all covered non-control candidate pairs, but those pairs share outcomes
within a fold and do not multiply the independent sample size. More Monte Carlo draws do not
create more realized gameweeks.

## Non-publication and the locked holdout

No probability, probability integral transform, scenario quantile or scenario count reaches a
member-facing surface, a ledger report line or a site payload. The mode names and the honesty
envelope of `docs/measurements_index.md` are unchanged; no mode is called safer or more
aggressive because of Phase E, and no product label with a proven meaning is attached to the
experimental arm. The locked 2025-26 holdout is not read, listed or hashed by E2, E3 or the
engine's tests.

## Explicit non-goals

- no search over K, ρ, α or N inside Phase E;
- no pool reduction before the solver;
- no re-optimization against scenario outcomes and no scenario-aware CP-SAT;
- no use of the legacy optimizer as engine or fallback;
- no member-facing output, probability or mode renaming;
- no multi-gameweek horizon, transfer state or chip logic;
- no new dependency, no GPU path, no second implementation of the game rules.

## Ownership

- Engine: candidate generator in `optimization`, selector and result contract in `scenarios`,
  and later the live shadow seam.
- Phase D boundary: the binding calibration verdict and the pin, an importable loader for the
  137 folds (pool, draw, realized points) and, only after a `calibrated_internal` verdict, the live draw
  builder.
- Evidence: this document, the adversarial contract tests, the E2 and E3 runners and
  artifacts, and the legacy removal audit.
