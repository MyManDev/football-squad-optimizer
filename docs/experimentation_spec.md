# Sprint 1 Experiment Parameter Contract

## Status and scope

This document began as the Sprint 0 contract for future Design of Experiments (DoE) and
Bayesian Optimization work. It defines candidate factors, response metrics, ownership,
and reproducibility requirements. Sprint 1 now implements the prepared-fold evaluation
subset documented in [the evaluation specification](evaluation_spec.md); temporal splitting,
parameter tuning, DoE, and Bayesian Optimization remain outside that runner.

Contract version: `0.2-draft`.

Only `bench_weight` is implemented in Sprint 0. Every other parameter in this document is
future-only and must not be accepted by the current optimizer. Future components must fail
explicitly when asked to activate an unsupported parameter; they must not silently ignore it.

## Separation of concerns

The candidate vector is partitioned by the component that gives each value meaning:

```text
theta_prediction = (form_window, fixture_weight)
theta_planning   = (horizon)
theta_risk       = (risk_penalty)
theta_optimizer  = (bench_weight)
```

Prediction factors control how projections are produced. Optimizer factors control how a
fixed projection table is converted into a decision. System-level experiment records must
store both groups, but a component must not reinterpret parameters owned by another
component.

## Parameter metadata contract

Every factor exposed to a future experiment runner must have these fields:

| Field | Meaning |
| --- | --- |
| `name` | Stable snake_case identifier |
| `owner` | Component responsible for its semantics and validation |
| `dtype` | Integer or floating-point representation |
| `unit` | Domain unit, or dimensionless when applicable |
| `baseline` | Control value used for comparison |
| `search_domain` | Values the experiment may propose |
| `hard_domain` | Values the owning component can validate safely |
| `domain_kind` | `discrete` or `continuous` search-space semantics |
| `status` | `active` or `future_only` |
| `activation_dependency` | Capability required before the factor can be activated |

The search domain may be narrower than the hard validation domain. Search-domain changes
are experiment-design decisions and must be versioned. Hard-domain changes are public
component contract changes and require tests.

## Candidate parameters

The following domains are provisional starting points. Data and prediction owners must
review them before the first experiment; unresolved semantics block activation but do not
block Sprint 0 completion.

| Name | Owner | Type | Unit | Baseline | Provisional search domain | Hard domain | Domain kind | Status |
| --- | --- | --- | --- | ---: | --- | --- | --- | --- |
| `form_window` | Prediction pipeline | Integer | Completed matches | 5 | `{3, 4, ..., 10}` | Positive integer | `discrete` | `future_only` |
| `fixture_weight` | Projection model | Float | Dimensionless blend | 0.5 | `[0.0, 1.0]` | `[0.0, 1.0]` | `continuous` | `future_only` |
| `horizon` | Planning optimizer | Integer | Gameweeks | 1 | `{1, 2, ..., 6}` | Positive integer | `discrete` | `future_only` |
| `risk_penalty` | Risk-aware optimizer | Float | Dimensionless coefficient | 0.0 | `[0.0, 2.0]` | Finite and non-negative | `continuous` | `future_only` |
| `bench_weight` | Baseline optimizer | Float | Objective weight | 0.1 | `[0.0, 0.25]` | `[0.0, 1.0]` | `continuous` | `active` |

### `form_window`

`form_window` is the number of completed historical matches used to construct form-related
features at a decision timestamp. The window must contain only information available before
that timestamp. The prediction pipeline owns minimum-history behavior, missing matches, and
whether team and player windows are aligned.

Activation dependency: a versioned feature-generation contract and time-aware historical
data pipeline.

### `fixture_weight`

`fixture_weight` is a convex blending weight for a normalized fixture component and a
normalized non-fixture component:

```text
combined_projection_component
    = (1 - fixture_weight) * non_fixture_component
    + fixture_weight * fixture_component
```

Both components must be defined on compatible scales before this factor is activated. This
convex-blend interpretation and its domain remain provisional until the prediction owner
reviews them. They may be revised while the contract is a draft. After activation under a
stable contract version, a materially different mathematical meaning requires a new name or
an explicit versioned migration rather than a silent semantic change.

Activation dependency: versioned projection components with compatible scaling.

### `horizon`

`horizon` is the number of future gameweeks represented by a planning model. A value of one
matches the temporal scope of Sprint 0, but the current optimizer does not expose this
parameter because it always solves exactly one gameweek. Values greater than one require a
new multi-gameweek formulation and must not be emulated by summing projections inside the
Sprint 0 interface.

Activation dependency: an explicitly reviewed multi-gameweek optimization specification.

### `risk_penalty`

`risk_penalty` is the coefficient `lambda` in a future risk-adjusted objective of the form:

```text
expected decision value - lambda * decision risk
```

The provisional contract assumes that `decision risk` is reported in points, for example a
standard-deviation measure, so `lambda` is dimensionless. The exact risk measure, covariance
treatment, and coefficient domain remain unresolved until an uncertainty contract exists.
The baseline value of zero represents risk-neutral optimization.

Activation dependency: calibrated uncertainty estimates and a reviewed risk formulation.

### `bench_weight`

`bench_weight` is already implemented by `OptimizationConfig`. It multiplies the projected
points of selected non-starters in the CP-SAT objective. The hard domain is the existing
validated interval `[0.0, 1.0]`; the narrower provisional search interval avoids assigning
the bench influence comparable to the starting lineup without explicit justification.

The public search domain is continuous, but the CP-SAT objective is quantized. For player
`i`, the effective integer bench coefficient is:

```text
ROUND_HALF_UP(bench_weight * scaled_points_i)
```

Consequently, distinct weights can produce identical coefficient vectors for a given
projection table and `expected_points_scale`. A future experiment runner must record the
scale and effective coefficient fingerprint for each evaluation fold. It should avoid
repeating candidates that are coefficient-equivalent across the compared folds. There is no
universal decimal step size because effective breakpoints depend on the projections and
scale.

Activation dependency: none. This is the only active factor in Sprint 0.

## Response metrics

Experiment responses evaluate a parameter configuration on unseen time periods. They are
not interchangeable with the objective optimized inside a single squad solve.

| Metric | Role | Direction | Aggregation | Definition |
| --- | --- | --- | --- | --- |
| `realized_squad_points` | Primary evaluation response | Maximize | Mean across rolling folds; also report dispersion | Realized decision score under a versioned scoring policy, using only decisions made before the evaluation gameweek |
| `projected_objective_value` | Diagnostic | None | Report distribution across successful folds | `OptimizationResult.objective_value` produced from pre-decision projections |
| `feasibility_rate` | Hard comparison constraint | Require `1.0` | Successful folds divided by attempted folds | Fraction of evaluation solves returning `OPTIMAL` or `FEASIBLE` |
| `solver_runtime_seconds` | Operational diagnostic | Minimize if promoted to a target | Median and 95th percentile across attempted folds | Wall-clock solve time for the full solve, including deterministic tie-breaking |
| `squad_turnover` | Optional stability diagnostic | None until a stability policy is approved | Mean across consecutive fold transitions | For fixed-size squads, `|S_t \ S_(t-1)|`: the number of player IDs entering the squad at time `t` |

The initial experiment objective should be the mean out-of-sample
`realized_squad_points` across rolling evaluation folds. Dispersion across folds must also be
reported. `projected_objective_value` must not be the sole DoE or Bayesian Optimization
target because it measures the model's own projections rather than unseen outcomes.

The implemented `realized_squad_points_v1` policy sums the frozen starting XI and adds the
captain's realized points a second time. Bench points and automatic substitutions are
excluded. Missing selected-player outcomes fail validation instead of being imputed or
converted to zero. Full semantics and aggregate definitions are in
[the evaluation specification](evaluation_spec.md).

Configurations with a feasibility rate below `1.0` are invalid for comparison unless an
experiment specification explicitly studies infeasibility. Runtime and turnover remain
separate responses until a reviewed multi-objective or constrained-optimization policy is
defined; they must not be combined through undocumented weights.

Exceptions and invalid configurations mark a trial as failed; they must not be converted to
zero-valued responses. `INFEASIBLE` and solution-free `UNKNOWN` outcomes count as feasibility
failures, and no projected or realized score may be fabricated for those folds. Missing
realized outcomes require a versioned exclusion policy, and every aggregate must record its
attempted and observed fold counts.

## Time-based evaluation and leakage control

Experiments must use rolling-origin or expanding-window evaluation. Random row-level splits
are not valid for football time-series evaluation.

The prepared-fold evaluator assumes this ordering but does not construct or certify it.
Issue #6 owns the split helper that will satisfy this requirement.

For every evaluation decision timestamp:

1. Feature construction may use only observations available before the timestamp.
2. Projection training and calibration may use only earlier periods.
3. Fixture information must be versioned as it was known at the timestamp.
4. The squad decision must be frozen before realized outcomes enter the dataset.
5. Metrics must be calculated from the frozen decision and later outcomes.

All candidate configurations in a comparison must use identical evaluation timestamps,
data snapshots, scoring rules, and missing-data policy.

## Fixed controls and nuisance variables

Parameters not selected as experimental factors must remain fixed across every candidate in
a comparison. The run record must still contain their values so a result is not attributed
to the wrong factor vector.

For the Sprint 0 optimizer, the fixed control vector includes:

- `budget_tenths`;
- `squad_size` and `squad_position_limits`;
- `starting_size`, `starting_position_min`, and `starting_position_max`;
- `max_players_per_team`;
- `expected_points_scale`;
- `solver_time_limit_seconds`;
- `deterministic_seed`;
- CP-SAT worker count, fixed to one by the baseline optimizer.

Dataset version, evaluation folds, scoring policy, missing-data policy, and projection-table
schema are also controlled inputs. If an experiment intentionally varies one of these
values, it must be promoted to an explicit factor or blocking variable under a versioned
experiment specification.

Runtime comparisons additionally require the same execution environment. At minimum, the
operating system, CPU model, logical-core count, Python version, solver version, worker
count, and solver time limit must be recorded. Runtime results from materially different
environments must be stratified rather than pooled without qualification.

## Baseline comparison

Every future experiment must include a named control configuration. The initial control is:

```text
form_window   = 5              # future-only, provisional
fixture_weight = 0.5           # future-only, provisional
horizon       = 1              # future-only, implicit in Sprint 0
risk_penalty  = 0.0            # future-only, risk-neutral
bench_weight  = 0.1            # active Sprint 0 default
```

Until future-only parameters are implemented, the executable baseline consists solely of
the current `OptimizationConfig`, including `bench_weight=0.1`. Documentation must not imply
that the other values are accepted by the Sprint 0 public interface.

## Reproducibility record

Each future experimental run must record at least:

- a unique `experiment_id` and UTC creation time;
- repository commit SHA and experiment-contract version;
- dataset snapshot or immutable dataset version;
- training and evaluation timestamp boundaries;
- scoring-policy version;
- complete prediction and optimization parameter values;
- the complete fixed control vector, including the full `OptimizationConfig`;
- random seeds for data, model, experiment design, and solver components;
- operating system, CPU model, logical-core count, and solver worker count;
- Python, solver, and relevant dependency versions;
- one result row per evaluation fold, including solver status;
- aggregated response metrics and failed-run diagnostics.

An experiment configuration must be serializable without relying on mutable notebook state.
The same record should be sufficient to reconstruct the run in a clean environment, subject
to documented solver and hardware limitations.

## Ownership and change control

| Area | Responsible component | Review required from |
| --- | --- | --- |
| Historical windows and feature availability | Data and prediction pipeline | Data, optimization |
| Projection-component semantics | Prediction model | Data, optimization |
| Planning horizon and risk objective | Optimization | Data, software integration |
| Experiment record and configuration transport | Software integration | Data, optimization |
| Response computation and scoring policy | Evaluation pipeline | All owners |

Changing a parameter's meaning requires a new parameter name or a versioned contract change.
Changing a baseline or search domain requires an experiment-specification revision. Current
Sprint 0 optimizer defaults must not be changed as a side effect of this document.

## Deferred decisions

The following decisions remain intentionally unresolved:

- automatic-substitution, bench-order, and alternative scoring-policy semantics;
- the exact form features governed by `form_window`;
- normalization of fixture and non-fixture projection components;
- the uncertainty measure used by `risk_penalty`;
- multi-gameweek state, transfer, and discounting rules for `horizon > 1`;
- the final DoE design, Bayesian Optimization surrogate, and acquisition function;
- production experiment storage and orchestration.

These items require separate issues and reviewed contracts before implementation.

## Non-goals for Sprint 0

- running or tuning experiments;
- adding experiment-tracking dependencies;
- training projection models;
- implementing uncertainty or covariance estimates;
- implementing multi-gameweek optimization;
- adding DoE or Bayesian Optimization code;
- changing `optimize_squad` or `OptimizationConfig`.
