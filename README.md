# Football Squad Optimizer

A data-source-independent decision-support package for selecting a football squad from
player projections. Sprint 0 implements a tested, single-gameweek baseline with Google
OR-Tools CP-SAT. Sprint 1 adds leakage-safe walk-forward evaluation, a pinned real-data
adapter, cross-season carry-over, and opening-gameweek projections. Sprint 2 adds a
development-only `4 x 3` screening experiment for `form_window` and `bench_weight`, plus a
separately guarded frozen-candidate holdout. Sprint 3 adds leakage-safe split-conformal
player-level prediction intervals and a locked-holdout calibration benchmark. Sprint 4 adds
conformal lower-bound risk-aware optimization and expanding-season development screening.
Sprint 5 adds a model-neutral prediction hand-off with provenance and player-adaptive
uncertainty from chronologically split residual history. Sprint 6 adds an open-source,
deterministic Ridge reference model and a paired baseline-versus-learned development
benchmark. Sprint 7 adds deterministic hierarchical empirical Monte Carlo scenarios and
fixed-decision score-distribution summaries. Sprint 13 adds a joint-scenario expected-score
and empirical lower-tail CVaR optimizer. Sprint 14 adds deterministic multi-gameweek squad and
transfer planning with explicit bank and free-transfer state. Sprint 15 adds deterministic
Gaussian-process Bayesian Optimization for development-only policy search. Automatic promotion
remains out of scope.

## Sprint 0 scope

Given a canonical pandas `DataFrame`, the optimizer selects:

- a 15-player squad;
- an 11-player starting lineup;
- an unordered bench;
- exactly one captain from the starting lineup.

The optimization module does not fetch data or calculate projections. Separate data,
feature, and baseline-prediction modules prepare the canonical projection table consumed by
the optimizer.

## Requirements and installation

Python 3.11 or newer is required. Create and activate a repository-local environment,
then install the package and its development tools (the activation command differs by shell):

```console
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[api,dev]"
```

The editable install provides the cross-platform `squadopt` command. Live operations use
`squadopt gameweek decide`, `squadopt gameweek settle --gameweek NN`, or
`squadopt season tick`; see the [opening-week runbook](docs/opening_week_runbook.md).
Research-only installations may omit the `api` extra. To serve the read-only backend from
the repository root, run:

```console
python -m uvicorn squadopt.api:app --host 127.0.0.1 --port 8000
```

## Canonical player schema

| Column | Contract |
| --- | --- |
| `player_id` | Unique, non-null; consistently integer or string |
| `name` | Non-empty string |
| `team_id` | Non-null; consistently integer or string |
| `position` | One of `GK`, `DEF`, `MID`, `FWD` |
| `price_tenths` | Non-negative integer, e.g. `55` means `5.5` |
| `expected_points` | Finite, numeric, and non-negative |

Additional columns are preserved in result tables. Input data is never modified in place.

## Usage

The following small configuration is intentionally smaller than the default 15-player squad
so the complete synthetic example remains readable:

```python
import pandas as pd

from squadopt import OptimizationConfig, optimize_squad

players = pd.DataFrame(
    [
        ["GK_A", "Synthetic GK A", "T1", "GK", 50, 5.0],
        ["GK_B", "Synthetic GK B", "T2", "GK", 50, 1.0],
        ["DEF_A", "Synthetic DEF A", "T3", "DEF", 50, 4.0],
        ["DEF_B", "Synthetic DEF B", "T4", "DEF", 50, 1.0],
        ["MID_A", "Synthetic MID A", "T5", "MID", 50, 10.0],
        ["MID_B", "Synthetic MID B", "T6", "MID", 50, 1.0],
        ["FWD_A", "Synthetic FWD A", "T7", "FWD", 50, 6.0],
        ["FWD_B", "Synthetic FWD B", "T8", "FWD", 50, 1.0],
    ],
    columns=[
        "player_id",
        "name",
        "team_id",
        "position",
        "price_tenths",
        "expected_points",
    ],
)

config = OptimizationConfig(
    budget_tenths=200,
    squad_size=4,
    squad_position_limits={"GK": 1, "DEF": 1, "MID": 1, "FWD": 1},
    starting_size=3,
    starting_position_min={"GK": 1, "DEF": 0, "MID": 0, "FWD": 1},
    starting_position_max={"GK": 1, "DEF": 1, "MID": 1, "FWD": 1},
    max_players_per_team=4,
)

result = optimize_squad(players, config)

if result.has_solution:
    print(result.selected_squad)
    print(result.starting_xi)
    print(result.bench)
    print(result.captain)
    print(result.total_cost_tenths)
    print(result.projected_score)
    print(result.objective_value)
else:
    print(result.solver_status)
```

### Canonical CSV integration

A local CSV that already follows the canonical schema can be passed through the thin
integration adapter:

```python
from squadopt import OptimizationConfig, optimize_squad_from_csv

result = optimize_squad_from_csv("predictions.csv", OptimizationConfig())

if result.has_solution:
    print(result.selected_squad)
    print(result.starting_xi)
    print(result.bench)
    print(result.captain)
```

The adapter reads UTF-8 CSV data, preserves identifiers as text, parses the numeric contract
columns, and delegates to `optimize_squad`. It does not fetch data, rename columns, normalize
positions, convert decimal prices, or calculate projections. `price_tenths` must therefore
contain whole-number tenths such as `55`, not `5.5`.

Valid data that cannot satisfy the optimization constraints returns a structured
`INFEASIBLE` result. Invalid schema or configuration raises a domain-specific validation
exception.

## Data pipeline

The example above hand-writes its player table. The data layer produces that table
from local player-gameweek records instead, without the optimizer knowing anything
about source column names, cleaning rules, or feature windows.

```text
local CSV / Parquet
  -> canonical player-gameweek dataset    (season, gameweek, player_id)
  -> leakage-safe rolling features
  -> baseline expected points
  -> optimizer-ready projection table     (one target gameweek)
```

```python
from squadopt import OptimizationConfig, optimize_squad
from squadopt.data import build_canonical_dataset, load_csv
from squadopt.features import build_feature_dataset
from squadopt.prediction import build_projection_table

canonical = build_canonical_dataset(load_csv(raw_path), adapter=adapter)
features = build_feature_dataset(canonical)
projections = build_projection_table(features, season="2025-26", gameweek=6)

result = optimize_squad(projections, OptimizationConfig())
```

A runnable version against the committed synthetic sample:

```powershell
.venv\Scripts\python -m scripts.run_pipeline_demo
```

### Real historical data

Six seasons of real player-gameweek data, 2020-21 through 2025-26, come from the
[vaastav archive](https://github.com/vaastav/Fantasy-Premier-League). The data is **not
committed** — its licensing does not permit redistribution — so it is fetched from a
pinned commit and verified against a committed checksum manifest, which is what keeps
every machine on identical bytes:

```powershell
.venv\Scripts\python -m scripts.fetch_historical_data
.venv\Scripts\python -m scripts.recommend_opening_squad
.venv\Scripts\python -m scripts.run_opening_prior_backtest
.venv\Scripts\python -m scripts.run_baseline_benchmark
```

The second command produces an opening-gameweek squad: 15 players, a starting eleven, a
bench, and a captain, with the pinned archive commit printed alongside so the result can
be reproduced. Players with usable earlier-season history use a decayed carry-over;
newcomers use the fitted deadline-price prior
`0.29940564635958394 * price_tenths / 10`.

The third command reproduces that coefficient on 2020-21 through 2024-25 and compares
price-only, carry-over-plus-constant, and carry-over-plus-price rules on the untouched
2025-26 opening gameweek. Reports are written under ignored `artifacts/opening_prior/`.

The fourth command uses 2020-21 through 2024-25 as historical context and evaluates the
baseline out of sample on 2025-26. It deliberately excludes GW1, which has a different
information set and remains covered by the opening-projection workflow. Repeat `--season`
to evaluate additional seasons. To persist the complete provenance and per-fold results:

```powershell
.venv\Scripts\python -m scripts.run_baseline_benchmark `
  --json-output docs\baseline_benchmark.json `
  --markdown-output docs\baseline_benchmark.md
```

The test suite never needs this data. Every test is synthetic and offline, including the
tests for the archive adapter, so continuous integration stays independent of it.

Two rules govern the layer. **Prices stay integer tenths** end to end, converted
with decimal arithmetic rather than binary floats. **Features for gameweek `t` use
only earlier gameweeks**: every rolling aggregation is grouped by season and player
and shifted by one gameweek before its window is applied, and that property is
proven by tests that mutate future results, truncate the future entirely, and check
season boundaries — not merely asserted in a comment.

| Document | Contents |
| --- | --- |
| [Data contract](docs/data_contract.md) | Canonical and projection schemas, time-of-knowledge rules, guarantees |
| [Data dictionary](docs/data_dictionary.md) | Every column: type, meaning, missing-value policy, leakage risk |
| [Data pipeline](docs/data_pipeline.md) | Stage responsibilities, leakage controls, determinism, testing |
| [Follow-up work](docs/data_followups.md) | Deliberate Sprint 0 gaps and how to close them |
| [Evaluation specification](docs/evaluation_spec.md) | Prepared folds, realized scoring, aggregation, limitations |

The synthetic sample under `data/sample/` is generated from code and contains no
third-party data; see [its notes](data/sample/README.md).

## Prepared-fold evaluation

The evaluator accepts chronologically ordered gameweek folds. Each fold
contains the projection table available when the decision was made and the matching
`player_id`/`total_points` outcomes observed later:

```python
from squadopt import EvaluationConfig, EvaluationFold, evaluate_prepared_folds

fold = EvaluationFold(
    fold_id="2025-26-GW06",
    projections=projections,
    realized_points=realized_points,
    metadata={"season": "2025-26", "gameweek": 6},
)

evaluation = evaluate_prepared_folds(
    [fold],
    EvaluationConfig(run_metadata={"dataset_version": "synthetic-v1"}),
)

print(evaluation.folds[0].realized_squad_points)
print(evaluation.summary.feasibility_rate)
```

The versioned `realized_squad_points_v1` policy sums the starting XI and adds the captain's
score a second time. It excludes bench points and automatic substitutions. The evaluator
does not train projections. `squadopt.backtest.build_walk_forward_folds` prepares folds
using only information available at each decision, while
`squadopt.backtest.run_baseline_benchmark` composes preparation and evaluation under a
versioned baseline contract.

## Sprint 2 screening experiment

The screening runner evaluates the full factorial
`form_window={3,5,7,10} x bench_weight={0.0,0.1,0.25}` on development seasons
`2021-22` through `2024-25`. It excludes opening gameweeks and does not read the locked
`2025-26` holdout. It reports paired improvements against the `(5, 0.1)` control,
season-aware moving-block bootstrap intervals, marginal effects, interactions, and the
pre-registered promotion gates.

```powershell
.venv\Scripts\python -m scripts.run_screening_doe
```

That command writes local JSON/Markdown reports and a small frozen-candidate artifact under
`artifacts/sprint2/`. Review the development result first. The holdout is an explicit second
operation and accepts only that frozen artifact:

```powershell
.venv\Scripts\python -m scripts.run_frozen_holdout
```

Distinct float weights are treated as equivalent only when the optimizer's exact
`ROUND_HALF_UP` integer coefficient fingerprints match over every compared fold. Projection
folds are cached once per `form_window`. Up to three independent candidate cells run in
parallel, while every CP-SAT solve itself remains single-worker and deterministic. See the
[screening experiment specification](docs/experimentation_spec.md) for the design,
bootstrap, promotion policy, holdout guard, and limitations.

## Sprint 3 projection uncertainty

Sprint 3 fits position-conditional split-conformal intervals on development-season player
residuals and applies the frozen calibration to the locked `2025-26` benchmark season
without refitting. Point projections are not changed. Groups with too little history use a
deterministic pooled
fallback, and negative lower bounds remain valid because realized fantasy points can be
negative.

```powershell
.venv\Scripts\python -m scripts.run_uncertainty_benchmark
```

The command writes reproducible JSON and Markdown reports under ignored
`artifacts/sprint3/`. The pinned benchmark uses `101,447` development residuals and obtains
`0.908301` empirical coverage for a `0.90` target over `28,648` holdout player-gameweeks.
See the [uncertainty specification](docs/uncertainty_spec.md) for the finite-sample quantile,
public contracts, validation, metrics, and limitations.

## Sprint 4 risk-aware optimization

Sprint 4 blends each unchanged point projection with its calibrated conformal lower bound.
`risk_aversion=0` reproduces the Sprint 0 objective exactly; `risk_aversion=1` uses the full
lower bound. The feasible set and CP-SAT implementation remain shared with the baseline.

```powershell
.venv\Scripts\python -m scripts.run_risk_screening
```

The screening uses expanding completed-season calibration over `2021-22` through `2024-25`,
does not access the reused `2025-26` benchmark, and performs no automatic promotion. Reports
are written under ignored `artifacts/sprint4/`. On 110 development folds, none of the three
risk-averse candidates improved mean or declared downside score over the `risk_aversion=0`
control, so the control remains the operational default. See the
[risk optimization specification](docs/risk_optimization_spec.md) for the objective,
leakage boundary, metrics, and limitations.

## Sprint 5 prediction integration and player-adaptive uncertainty

External prediction models now hand off only `player_id` and `expected_points`. The
`prepare_optimizer_projection` boundary exact-aligns those values with deadline-known player
fields and returns a fingerprinted `PredictionSnapshot`; walk-forward folds preserve its
model, feature, training-cutoff, and data provenance.

The adaptive uncertainty contract learns player residual standard deviations on the earlier
part of completed historical folds, shrinks supported player estimates toward their position
scale, and learns standardized conformal multipliers on a later, disjoint calibration part.
Thin or unseen players use deterministic position or pooled fallback. Point projections and
the Sprint 0 feasible set remain unchanged.

```powershell
.venv\Scripts\python -m scripts.run_player_risk_screening
```

The command screens fixed risk levels only over `2021-22` through `2024-25`, writes ignored
reports under `artifacts/sprint5/`, does not access `2025-26`, and performs no automatic
promotion. The current real-data command uses the deterministic baseline through the same
model-neutral boundary; a learned model can replace it without changing the optimizer.
On 110 development folds, player-adaptive risk changed 89 to 110 squads depending on the
risk level, but every risk-averse candidate underperformed the point-objective control on
the declared mean and downside diagnostics; no candidate was promoted.
See the [Sprint 5 specification](docs/player_uncertainty_spec.md) for the contracts,
formulation, leakage boundary, fallback policy, and limitations.

## Sprint 6 learned prediction reference

Sprint 6 fits a standardized Ridge model at each walk-forward decision using only rows
strictly before that gameweek. The model consumes deadline-safe shifted form, prior-season
carry-over, price, and fixed position indicators. Missing features use training-only medians
(or zero when a whole training column is missing), and negative predictions are floored at
zero before entering the optimizer contract.

```powershell
.venv\Scripts\python -m scripts.run_learned_benchmark
```

The command compares baseline and Ridge predictions on identical folds over `2021-22`
through `2024-25`, writes ignored JSON and Markdown artifacts under `artifacts/sprint6/`,
and exposes the Ridge out-of-sample residual history for later scenario generation. It does
not access the locked `2025-26` holdout and never promotes the reference model automatically.
Ibrahim's production model can later replace Ridge through the unchanged
`PredictionSnapshot` boundary. See the
[learned prediction specification](docs/learned_prediction_spec.md).

The verified `2024-25` smoke benchmark produced 37/37 feasible paired folds and 26,303
out-of-sample player residuals. Ridge reduced RMSE from `2.1172` to `1.9861`, increased MAE
slightly from `1.0610` to `1.0705`, and improved the mean realized squad score by `4.8108`
points per gameweek in that development season. The run took about ten minutes on the
development machine; this is an offline evidence run, not a live-deadline latency target.
No promotion decision follows from this single-season result.

## Sprint 7 Monte Carlo scenarios

Sprint 7 turns historical out-of-sample residuals into joint player-point scenarios. Each
draw combines a shared gameweek component, a shared team-within-gameweek component, and a
player-adaptive empirical idiosyncratic component with position and pooled fallbacks. The
point-projection table is unchanged, while scenario values may be negative.

```powershell
.venv\Scripts\python -m scripts.run_scenario_benchmark
```

The real-data smoke command uses learned residuals from `2024-25` GW2 through GW9 to
simulate 2,000 outcomes for GW10. It then evaluates the already-fixed squad, starting XI,
and captain; it does not run one optimizer per scenario. The verified run produced a mean
score of `57.2937`, population standard deviation `11.8587`, lower 10% quantile `42.6896`,
and mean worst-10% score `37.1641`. The locked `2025-26` holdout was not accessed. See the
[scenario specification](docs/scenario_spec.md).

## Sprint 13 scenario-aware optimization

Sprint 13 optimizes one shared squad, starting XI, bench, and captain directly against a
validated `ScenarioSet`. The objective is a convex blend of mean starting score and empirical
lower-tail CVaR, plus the existing expected bench-quality term. It does not choose a different
squad per scenario.

```python
from squadopt import OptimizationConfig
from squadopt.scenarios import ScenarioOptimizationConfig, optimize_scenario_aware_squad

result = optimize_scenario_aware_squad(
    scenarios,
    OptimizationConfig(),
    ScenarioOptimizationConfig(risk_aversion=0.25, tail_fraction=0.10),
)

if result.optimization_result.has_solution:
    print(result.optimization_result.selected_squad)
    print(result.mean_scenario_score, result.cvar_score)
```

The feasible set, integer point scaling, deterministic seed, one-worker solver policy, and
secondary tie-break are shared with the baseline. See the
[scenario-aware optimization specification](docs/scenario_optimization_spec.md).

## Sprint 14 transfer planning

Sprint 14 extends the legal squad decision across consecutive gameweeks. The input horizon
supplies projections and integer buy/sell prices; the optimizer maintains squad continuity,
bank, free-transfer carry, transfer hits, XI, bench, and captain decisions.

```python
from squadopt import OptimizationConfig
from squadopt.planning import (
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    optimize_transfer_plan,
)

result = optimize_transfer_plan(
    PlanningHorizon(horizon_table),
    InitialSquadState(initial_player_ids, bank_tenths=5, free_transfers=1),
    OptimizationConfig(),
    TransferPlanningConfig(horizon_discount_factor=0.98),
)

if result.has_solution:
    for week in result.weeks:
        print(week.gameweek, week.transfers_in, week.transfers_out)
```

See the [transfer-planning specification](docs/transfer_planning_spec.md).

## Sprint 15 Bayesian Optimization

Sprint 15 searches a finite, versioned policy grid with a seeded maximin initial design, a fixed
Matern Gaussian-process surrogate, and Expected Improvement. The evaluator receives only the
declared chronological development fold IDs; locked-holdout IDs are recorded but never passed to
it.

```python
from squadopt.bayesopt import BayesianOptimizationConfig, run_bayesian_optimization


development_fold_ids = ("2023-24-gw10", "2023-24-gw11", "2024-25-gw10")
locked_holdout_fold_ids = ("2025-26-gw10",)


def development_objective(candidate, development_fold_ids):
    # Adapt the existing chronological development-fold evaluation here.
    return evaluate_policy(candidate.values, development_fold_ids)


result = run_bayesian_optimization(
    development_objective,
    development_fold_ids,
    BayesianOptimizationConfig(evaluation_budget=30, deterministic_seed=0),
    locked_holdout_fold_ids=locked_holdout_fold_ids,
)

print(result.recommended_candidate.values)
```

The result is a recommendation only. See the
[Bayesian Optimization specification](docs/bayesian_optimization_spec.md).

## Live deadline recommendation

The live command reads an immutable deadline capture and uses the operational control. Risk
diagnostics are optional and require an explicitly identified, matching out-of-sample
residual export:

```powershell
.venv\Scripts\python -m scripts.recommend_current_squad
```

Without residual evidence the structured risk state is `not_requested`. A requested risk
calculation returns `unavailable` when the model identity, opening-gameweek evidence, or
minimum history is missing; it never prints fabricated lower-tail metrics. See the
[live risk diagnostics specification](docs/live_risk_diagnostics_spec.md).

## Calendar-aware residual measurement

Before uncertainty and scenarios are recalibrated, compare the calendar-blind and
calendar-aware residual regimes on identical player/fold rows and split the result by blank,
single, and double-plus fixture counts:

```powershell
.venv\Scripts\python -m scripts.run_calendar_recalibration `
  --reference-residuals artifacts/calendar_blind.csv `
  --candidate-residuals artifacts/calendar_aware.csv `
  --json-output artifacts/calendar_recalibration.json `
  --markdown-output artifacts/calendar_recalibration.md
```

Without extra flags this command produces a measurement artifact only. Add `--time-aware`
to use disjoint chronological scale-training, conformal-calibration, and evaluation slices;
that report compares held-out coverage/width by fixture count, double-gameweek player scales,
and common/team/idiosyncratic scenario-component spread. Neither mode infers
opening-gameweek uncertainty from GW2+ residuals.
See the [calendar recalibration specification](docs/calendar_recalibration_spec.md).
The [residual export contract](docs/residual_export_contract.md) and
[recalibration runbook](docs/recalibration_runbook.md) define the cross-owner handoff and
execution sequence.

## Multi-gameweek projection horizon

The transfer planner consumes a validated `PlanningHorizon`; the prediction side produces
the `ProjectionHorizon` it converts from. One call projects every requested gameweek from a
single captured decision snapshot:

```powershell
.venv\Scripts\python -m scripts.build_projection_horizon --from-gameweek 1 --gameweeks 4
```

One information state covers the whole horizon: player features come from the decision
point and never move, and only the calendar varies per gameweek. A blank gameweek is a row
with zero fixtures projecting exactly zero points; a double scales linearly, under
`linear_fixture_count_scaling_v1`, which is post-processing applied on top of a
calendar-blind control rather than something the model learned.

A one-gameweek horizon reproduces `recommend_current_squad`'s projection exactly. See
[the recorded run](docs/projection_horizon_run.md) — including why an opening capture
produces a flat horizon, which is the honest answer rather than a defect.

This is planning input, **not gate evidence**: the frozen objective is single-gameweek
realized squad points.

How far a longer projection drifts is measured separately:

```powershell
.venv\Scripts\python -m scripts.run_horizon_decay
```

One projection is made at every chronological development decision point and scored
against that gameweek and each of the next few, applying the same fixture-count scaling
the horizon ships. See [the recorded measurement](docs/horizon_decay.md). It reports what
the drift is; choosing a horizon length on that evidence is a separate decision.

## Signal the control has not spent

Opponent strength is estimated from shifted results in `squadopt.features.strength` and no
projection consumes it. Whether that is a missed opportunity is a measurement rather than
an opinion:

```powershell
.venv\Scripts\python -m scripts.run_opponent_strength_signal
```

It attaches the estimate to the control's out-of-sample residuals and reports how they
move with it, separately for the attacking and defensive sides. A residual that still moves
with something the model could have seen is signal not yet spent. See
[the recorded measurement](docs/opponent_strength_signal.md).

Not gate evidence and not a candidate: consuming opponent strength changes the
expected-points rate and needs its own declaration and a single run under the frozen gates.

## Residual exports for the recalibration pair

Both halves of the pair are produced by one command at one commit, because the pairing
rule requires both manifests to name the same `repository_commit`:

```powershell
.venv\Scripts\python -m scripts.export_candidate_residuals --candidate learned
```

`--candidate learned` exports the Issue #43 learned-rate candidate, whose manifest carries
that candidate's own model identity; `--candidate production` exports the already-measured
two-stage regime the recalibration CLI names by default. Each run rebuilds the
calendar-blind control export and checks the single-artifact and pair preflights before
reporting success. The tables stay local — they are derived from third-party data — and
the committed record is [the export summary](docs/candidate_residual_export.md).

## The Issue #43 learned-rate candidate

The candidate changes one component, the expected-points rate, which is fitted per fold on
the expanding visible history from the shifted rolling points-per-90 feature together with
fixture count, home fixture count, appearance rate, and minutes per appearance. Every other
component is reached through the existing code rather than reimplemented, so "only the rate
changed" is checkable rather than asserted.

```powershell
.venv\Scripts\python -m scripts.freeze_candidate_declaration
```

This prints and records the declaration with its two fingerprints for Stage A of
[the declaration review](docs/candidate_declaration_review.md). No formal gate run may
precede that freeze. See [the frozen declaration](docs/issue43_candidate_declaration.md).

Historical opening-gameweek residuals cannot be produced under the live availability
contract; [the GW1 blocker report](docs/gw1_blocker_report_2021-2026.md) records why, which
is the accepted deliverable for that checklist item.

## Quality checks

```powershell
.venv\Scripts\python -m pytest -n auto --dist loadscope
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy src\squadopt
```

The full suite is the merge gate, and it runs in parallel: 115 s against 444 s serial on eight
workers, with the same 2,502 passed and 1 skipped either way. `-n auto` counts physical cores,
so it picks fewer workers than a thread count suggests, and it is not in `addopts` — a single
`pytest path::test` stays serial and starts instantly.

Two pytest markers split the suite: `slow` (solver-heavy tests of more than about five
seconds each) and `integration` (everything under `tests/integration`, applied
automatically). `-m "not slow"` is no longer the useful shortcut it was — it saves about
112 s serially, so the parallel full suite beats it outright and gates on everything.
[Branching and protection](docs/architecture/branching.md) records the measurements and why
`loadscope` is the chosen distribution.

See [the optimization specification](docs/optimization_spec.md) for the formulation,
rounding rules, deterministic tie-breaking, assumptions, and current limitations.
The [screening experiment specification](docs/experimentation_spec.md) records the
implemented Sprint 2 DoE, frozen holdout protocol, and deferred Bayesian Optimization work.
The [uncertainty specification](docs/uncertainty_spec.md) records the implemented Sprint 3
calibration contract that later scenario and risk-aware optimization work can consume.
The [risk optimization specification](docs/risk_optimization_spec.md) records the Sprint 4
conformal lower-bound objective and development-only expanding-season screening protocol.
The [Sprint 5 specification](docs/player_uncertainty_spec.md) records the model-neutral
prediction provenance boundary and player-adaptive standardized conformal calibration.
The [Sprint 6 specification](docs/learned_prediction_spec.md) records the deterministic
Ridge reference, expanding-window fit, paired benchmark, and production-model integration
boundary.
The [Sprint 7 specification](docs/scenario_spec.md) records the empirical hierarchical
bootstrap, player-scale fallback, scenario fingerprint, and fixed-decision risk summaries.
The [Sprint 13 specification](docs/scenario_optimization_spec.md) records the joint-scenario
mean/CVaR objective, integer reformulation, deterministic tie-break, and limitations.
The [Sprint 14 specification](docs/transfer_planning_spec.md) records squad continuity, bank
accounting, free-transfer carry, horizon weighting, and current limitations.
The [Sprint 15 specification](docs/bayesian_optimization_spec.md) records the finite policy
space, maximin design, Matern surrogate, Expected Improvement, holdout boundary, and stopping
rules.
