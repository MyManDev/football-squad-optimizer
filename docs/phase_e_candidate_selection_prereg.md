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
| Separability bootstrap | B = 200 scenario resamples, `numpy.random.default_rng(0)`, 90% percentile interval |
| Candidate counts probed in E2 | K ∈ {4, 8, 16} |
| Operational budget | 120 seconds of wall clock per decision, candidate generation plus scoring, on the machine named in the E2 artifact |

ρ, α, N and K are not searched inside Phase E. Searching them is Phase G's work and needs its
own preregistration.

## Candidate set

**Identity.** A decision is identified by its starting eleven and its captain. The full
fifteen-player squad, the bench order and the vice-captain are completions: the squad is
whatever the deterministic model chooses under its own objective, and the bench order and
vice-captain follow `optimizer_projection_order_v1` unchanged. Two decisions with the same
eleven and captain are the same candidate.

Why not the full (squad, eleven, captain) triple: an unrecorded design probe on the GW3
2026-27 pool (651 players, no outcomes read) showed that excluding exact triples returns six
objective-tied bench swaps before the eleven changes once; excluding (eleven, captain) pairs
returned eight distinct elevens with objective gaps of −0.09 to −0.21 points at 0.33 to 0.50
seconds per solve. The risk trade-off Phase E is meant to see lives in the eleven and the
captain, so that is where the identity lives.

**Generation.** Candidate 0 is the control: the `optimize_squad` result, byte-identical to what
the live path publishes today, tie-break included. Candidate k is the solution of the same
model with one no-good constraint per earlier candidate j < k:

```text
sum(starter[i] for i in eleven_j) + captain[captain_j] <= 11
```

A decision equals candidate j exactly when that sum is 12, so the constraint excludes the pair
and nothing else. Each candidate solve uses the control's own procedure: primary solve, then
the lexicographic tie-break with the primary's solution as a hint. The pool is the complete
validated projection pool; `required_player_ids` stays available as a constraint seam and is
not used by Phase E itself.

**Completeness.** Every candidate's primary status must be `OPTIMAL`. A candidate whose
primary status is `FEASIBLE` or `UNKNOWN` makes the set incomplete and Phase E falls back. A
model that becomes `INFEASIBLE` after j no-goods has exhausted the legal decision space; that
is a complete set of size j, not a failure. If the control itself cannot be solved, the
existing error behaviour is kept and Phase E produces no result at all.

**Bounded loss.** Because candidates are ordered by the deterministic objective, no candidate's
objective lies below the control's by more than δ_K, the gap of the K-th candidate. Whatever
Phase E selects therefore costs at most δ_K expected points under the projection the control
itself trusts. δ_K is recorded on every decision and its distribution is an E2 field. This is
the property that makes the legacy optimizer's measured losses structurally impossible here.

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
- **Reported floats.** Mean and CVaR are reported per candidate as the same integer sums
  divided by the scale, so a reported number can be recomputed from the selection inputs.

**Separability.** When the argmax d* is not the control, the draw must prefer d* by more than
its own Monte Carlo noise. Scenario identifiers are resampled with replacement B = 200 times
under `numpy.random.default_rng(0)`; on each resample U_int is recomputed for d* and the control
and their difference recorded. If the 5th percentile of those differences is not strictly
positive, the result is `FALLBACK_NOT_SEPARABLE` and the control is returned. The bootstrap is
over scenarios only: it says the draw, not sampling noise, prefers d*. It claims nothing about
realized outcomes.

## Calibration pin

Phase E may only act on a draw whose provenance is on a pin of calibrated component and
sampler versions. The pin is a tuple constant declared beside `IN_SEASON_CONTROL_MODEL_VERSIONS`
in the application layer, empty until the binding Phase D component-squad calibration records
`passed`. A `failed` or `abstained` Phase D verdict leaves the pin empty. A draw whose
provenance is not on the pin yields `FALLBACK_PHASE_D_NOT_CALIBRATED`. The versions the pin
names are the Phase C component contract (`component_prediction_v1` today) and the sampler
contract (`component_scenario_foundation_v1` today); Phase D owns their exact spelling.

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
| `diagnostics` | the candidate table: rank, objective, deterministic gap, eleven overlap with the control, same captain, covered, mean, CVaR, `U_int`, and the separability interval for the argmax |

Statuses:

- `SELECTED`: a covered candidate was chosen; rank 0 when the control itself wins.
- `FALLBACK_NOT_SEPARABLE`: the argmax was not the control and the scenario bootstrap did not
  separate them.
- `FALLBACK_INCOMPLETE_CANDIDATES`: a candidate solve was not `OPTIMAL`.
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
- the number of distinct elevens and distinct captains among the candidates, and δ_K;
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
verdict artifact to exist. If that verdict is `failed` or `abstained`, E3 still runs and writes
its fields, but its verdict is `technical_only` and no gate below binds anything.

**Per fold.** Generate the candidates from the fold's Phase C decision roster, draw the fold's
scenarios once, select, and score the control and every covered candidate against the fold's
realized points and minutes with `score_frozen_squad_decision`, the same realized scorer the
Phase D calibration uses. Let D_f be the realized score of the selected decision minus the
realized score of the control; D_f is exactly zero on a fallback fold and that zero is kept,
because it is what the operator would have experienced.

**Gates**, all fixed here:

- **A, harm excluded.** The 90% fold-bootstrap interval of mean(D_f) over all 137 folds
  (B = 2000 resamples, `numpy.random.default_rng(0)`) has a lower bound above −1.0 points per
  gameweek.
- **R, reliability.** The frozen K produces a complete candidate set on at least 95% of folds,
  no fold raises, and every non-selected fold carries a named status.
- **U, usefulness.** The selection differs from the control on at least 20% of folds.
- **S, signal.** Over every (fold, covered candidate other than the control) pair, the Spearman
  correlation between the predicted utility difference to the control, in points, and the
  realized paired difference to the control has a positive point estimate and a 90%
  fold-cluster bootstrap interval that excludes zero.

**Reported, not gated:** mean(D_f) on all folds and on disagreement folds only, each with its
interval; season-level means; the mean of the worst 10% of folds by D_f; the realized lower
10% tail of the selected decisions against the control's across folds; counts of eleven,
captain and formation changes; status counts; solve and scoring time.

**Verdicts.** `harmful` when A fails. `inert` when A passes and U fails. `shadow_eligible` when
A and R pass and the Phase D verdict is `passed`; S is reported beside it as `signal: true` or
`signal: false` and does not change the verdict. `technical_only` when the Phase D verdict is
absent, `failed` or `abstained`.

`shadow_eligible` permits exactly one thing: E4, a shadow arm in the live decide phase that
computes the Phase E result and records it in the ledger diagnostics while the published
decision stays the control. Making Phase E the default is E5 and needs a new preregistration
that pools these 137 folds with settled prospective gameweeks.

## Power, stated before the run

Realized weekly points of regular starters in the four development seasons have a standard
deviation of 4.3 to 4.7, and the realized difference between two such starters in the same
gameweek has a standard deviation of about 6.2. Those are variance estimates only; no candidate
was evaluated to obtain them. At 137 folds the standard error of a one-swap paired mean is about
0.53 points, so a 90% interval excludes zero only for effects above roughly 0.87 points per
gameweek, while the candidates' deterministic gaps are 0.2 points or less. A superiority claim
is therefore not expected to be provable on this population and is not a gate. Gate A is the
only decision-level gate; gate S uses the K × 137 candidate pairs because that is where the
population has power. Computation does not change this: the noise is in the single realized
gameweek per fold, not in the Monte Carlo estimate.

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
  137 folds (pool, draw, realized points) and, only after a `passed` verdict, the live draw
  builder.
- Evidence: this document, the adversarial contract tests, the E2 and E3 runners and
  artifacts, and the legacy removal audit.
