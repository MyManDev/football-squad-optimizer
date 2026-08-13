# Football Squad Optimizer

A data-source-independent decision-support package for selecting a football squad from
player projections. Sprint 0 implements a tested, single-gameweek baseline with Google
OR-Tools CP-SAT. Sprint 1 adds leakage-safe walk-forward evaluation, a pinned real-data
adapter, cross-season carry-over, and opening-gameweek projections. Sprint 2 adds a
development-only `4 x 3` screening experiment for `form_window` and `bench_weight`, plus a
separately guarded frozen-candidate holdout. Model calibration and Bayesian Optimization
remain future work.

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

Python 3.11 or newer is required. Create a repository-local environment on Windows:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[dev]"
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

## Quality checks

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy src\squadopt
```

See [the optimization specification](docs/optimization_spec.md) for the formulation,
rounding rules, deterministic tie-breaking, assumptions, and current limitations.
The [screening experiment specification](docs/experimentation_spec.md) records the
implemented Sprint 2 DoE, frozen holdout protocol, and deferred Bayesian Optimization work.
