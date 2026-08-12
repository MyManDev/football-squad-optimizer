# Football Squad Optimizer

A data-source-independent decision-support package for selecting a football squad from
player projections. Sprint 0 implements a tested, single-gameweek baseline with Google
OR-Tools CP-SAT. Sprint 1 adds evaluation of caller-prepared gameweek folds without yet
implementing temporal splitting, model calibration, DoE, or Bayesian Optimization.

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
```

The second command produces an opening-gameweek squad: 15 players, a starting eleven, a
bench, and a captain, with the pinned archive commit printed alongside so the result can
be reproduced. It also reports how much of the squad rests on real history rather than a
fallback constant.

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

The evaluator accepts already-prepared, chronologically ordered gameweek folds. Each fold
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
does not create walk-forward splits or train projections; callers must prepare folds using
only information available before each decision timestamp.

## Quality checks

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy src\squadopt
```

See [the optimization specification](docs/optimization_spec.md) for the formulation,
rounding rules, deterministic tie-breaking, assumptions, and current limitations.
The [experiment parameter contract](docs/experimentation_spec.md) records provisional
Sprint 1 factors and evaluation rules without implementing DoE or Bayesian Optimization.
