# Sprint 2 Screening Experiment Specification

## Status and scope

This document defines the implemented Sprint 2 Design of Experiments contract.

Experiment contract version: `screening_doe_v1`.

Sprint 2 screens two already implemented factors against the deterministic baseline:

- prediction-owned `form_window`;
- optimizer-owned `bench_weight`.

It does not implement Bayesian Optimization, Gaussian Processes, uncertainty models,
Monte Carlo simulation, Markov models, reinforcement learning, fixture features, a learned
prediction model, or a multi-gameweek optimizer. Those capabilities require later contracts
and must not be inferred from this experiment runner.

## Public interface

The versioned interface lives under `squadopt.experiments`:

```python
from squadopt.experiments import (
    ScreeningExperimentConfig,
    freeze_screening_candidate,
    run_frozen_holdout,
    run_screening_experiment,
)

screening = run_screening_experiment(panel, ScreeningExperimentConfig())
frozen = freeze_screening_candidate(screening)
holdout = run_frozen_holdout(panel, frozen, screening.config)
```

`run_screening_experiment` reads only the development seasons. The locked holdout can be
read only through the separate `run_frozen_holdout` call, which requires a
`FrozenCandidate`. A frozen candidate records both the screening-result fingerprint and the
configuration fingerprint. Changing a comparison-affecting control invalidates it.

All public configuration and result records are frozen dataclasses. Caller-owned metadata
and projection tables are copied before use.

## Pre-registered factorial design

The screening design is a balanced `4 x 3` full factorial:

| Factor | Owner | Levels | Control level |
| --- | --- | --- | ---: |
| `form_window` | Prediction | `{3, 5, 7, 10}` completed matches | `5` |
| `bench_weight` | Optimization | `{0.0, 0.1, 0.25}` | `0.1` |

Every combination is evaluated, giving 12 candidate cells. The named control is
`form_window=5, bench_weight=0.1`.

The default time split is:

| Role | Seasons | Opening gameweek |
| --- | --- | --- |
| Development screening | `2021-22` through `2024-25` | Excluded |
| Locked holdout | `2025-26` | Excluded |

Gameweek 1 remains part of the separate opening-squad workflow because it has a different
information set. The screening configuration requires at least one earlier gameweek in the
same season.

## Executable factor mappings

### `form_window`

For one trial value `w`, `FormWindowMapping` produces:

```text
FeatureConfig(
    minutes_windows=(w,),
    points_windows=(w,),
    per_90_window=w,
    min_periods=1,
)
BaselineProjectionConfig(minutes_window=w, per_90_window=w)
```

The fixed `min_periods=1` rule is not an additional factor. Projection folds are constructed
once for each of the four `form_window` levels and cached in memory. The three
`bench_weight` cells at a window reuse those exact fold objects, ensuring identical
decision timestamps and avoiding repeated feature generation.

### `bench_weight`

`bench_weight` affects only the current one-gameweek CP-SAT objective:

```text
starter points
+ captain points
+ bench_weight * selected non-starter points
```

CP-SAT receives integer coefficients. Expected points use decimal `ROUND_HALF_UP`:

```text
scaled_points_i = ROUND_HALF_UP(expected_points_i * expected_points_scale)
bench_i = ROUND_HALF_UP(scaled_points_i * bench_weight)
```

The optimizer and experiment runner import the same coefficient functions; the rounding
rule is not reimplemented by the experiment layer.

For every fold, a SHA-256 fingerprint covers the stable player ordering, integer objective
coefficients, player team/position/price inputs, and fixed feasible-set controls. If two
weights at the same `form_window` produce the same fingerprints over all folds, the later
cell reuses the mathematically identical solve results. The artifact records both the
fingerprint and the source candidate. Raw float equality is never used as a substitute for
coefficient equality.

## Walk-forward evaluation

Each candidate uses the existing leakage-safe fold builder and prepared-fold evaluator:

1. A decision point is created for each eligible gameweek in chronological order.
2. Only rows visible at that decision point reach feature generation.
3. Rolling features are shifted, so the target gameweek's outcome cannot enter its own
   projection.
4. The squad, starting XI, bench, and captain are frozen by the optimizer.
5. The later realized outcome table scores the frozen starting XI and captain.

Every candidate in a comparison must have the same ordered `fold_id` sequence. Any mismatch
is an experiment execution error rather than a silently unpaired comparison.

The primary response is mean realized squad points under
`realized_squad_points_v1`. Projected objective value is diagnostic only and is never the
promotion target.

## Paired inference

Candidate responses are paired by exact `fold_id` against the control:

```text
d_t = realized_points(candidate, t) - realized_points(control, t)
```

The reported point estimate is the mean of `d_t`. Per-season paired means are also stored.

Serial dependence between adjacent gameweeks makes an independent-row bootstrap
inappropriate. The default uncertainty calculation is a deterministic, season-aware moving
block bootstrap:

- confidence level: `90%`;
- resamples: `5,000`;
- block length: `4` consecutive gameweeks;
- random seed: `0`, combined with a stable candidate-ID digest;
- blocks never cross season boundaries;
- each season is resampled to its original fold count before all seasons are pooled;
- percentile endpoints use linear interpolation.

The bootstrap is a screening uncertainty diagnostic, not a claim that the baseline residual
process is stationary across all seasons.

## Development promotion gates

A challenger is eligible for the locked holdout only when all gates pass:

1. candidate and control feasibility rates are exactly `1.0`;
2. every attempted fold has a paired realized response;
3. paired mean improvement is at least `+0.5` points per gameweek;
4. the 90% bootstrap confidence-interval lower bound is non-negative.

Among eligible challengers, the largest paired mean improvement is selected. Exact ties use:

1. lower mean squad turnover;
2. lower median solver runtime;
3. lexicographically smaller stable candidate ID.

If no challenger passes, the frozen decision retains the control. Runtime is only a tie-break
diagnostic; it is not blended into football points through an undocumented weight.

## Locked holdout gate

The holdout command evaluates only the frozen development choice and the named control on
`2025-26`. It applies the same feasibility, `+0.5` paired mean, and non-negative 90% lower
bound gates. A challenger is finally promoted only if it passes all holdout gates.

The holdout result cannot change which candidate was selected from development. It can only
accept or reject that one frozen challenger. Trying additional candidates after observing
holdout outcomes would invalidate the holdout and requires a new future season or a newly
declared evaluation protocol.

## Factorial summaries

For each factor level, the report calculates the balanced marginal mean over the other
factor and its difference from the control level's marginal mean.

For cell `(a, b)`, the two-factor interaction residual is:

```text
cell_mean(a, b)
- form_window_marginal(a)
- bench_weight_marginal(b)
+ grand_mean
```

These are descriptive screening effects. With only one configured cell per factor
combination, the gameweek folds provide repeated responses; there is no separate replicated
factorial randomization experiment.

## Artifacts and reproducibility

The development command writes:

- `artifacts/sprint2/screening.json`;
- `artifacts/sprint2/screening.md`;
- `artifacts/sprint2/frozen_candidate.json`.

The separate holdout command writes:

- `artifacts/sprint2/holdout.json`;
- `artifacts/sprint2/holdout.md`.

`artifacts/` is intentionally ignored by Git. Reports are reproducible run outputs, not
source files. A project decision may later copy an approved report into `docs/`.

The JSON records include:

- repository revision and dirty-tree flag;
- pinned archive repository, commit, and manifest checksum;
- experiment and feature-generation contract versions;
- full design, promotion policy, fixed optimizer controls, and seeds;
- platform, processor, logical CPU count, Python, pandas, and OR-Tools versions;
- one result row per candidate and fold, including solver status and runtime;
- coefficient signatures and reuse diagnostics;
- paired differences, confidence intervals, main effects, interactions, and decision reason.

Run the two stages explicitly:

```powershell
.venv\Scripts\python -m scripts.run_screening_doe
.venv\Scripts\python -m scripts.run_frozen_holdout
```

Do not run the second command until the development artifact has been reviewed and accepted
as frozen.

## Fixed controls and assumptions

The following are fixed across candidate cells:

- the canonical historical panel and pinned archive snapshot;
- chronological folds, scoring policy, and missing-history rules;
- cross-season decay and minimum-minutes settings;
- budget, squad and lineup sizes, position limits, team limit, and prices;
- expected-points scale, CP-SAT time limit, solver seed, and one solver worker;
- at most three independent candidate jobs; every individual CP-SAT solve still uses one
  worker and the declared deterministic seed;
- integer `ROUND_HALF_UP` coefficient construction and deterministic tie-breaking.

The design assumes that the historical panel exposes the configured development and holdout
seasons, projections remain comparable across factor cells, and realized outcomes exist for
every player selected in a scored fold.

## Known limitations and later work

- The deterministic projection baseline is not a learned predictive model.
- Fixture strength, availability news, transfers, chips, vice-captain fallback, automatic
  substitutions, and bench realized points are excluded.
- Runtime comparisons are hardware-sensitive even though provenance is recorded.
- A four-gameweek block is a declared screening choice, not a universally optimal dependence
  model.
- The current optimizer makes independent one-gameweek decisions and has no transfer state.

Future factors such as fixture weight, planning horizon, and risk penalty remain inactive.
Sprint 3 supplies the first versioned player-level uncertainty contract. Bayesian
Optimization should still begin only after that contract is reviewed as stable and a
continuous search space with worthwhile expensive evaluations is explicitly defined.
