# System Map

What the package contains today, how its parts depend on each other, and where the
dependencies still point the wrong way. Measured, not asserted: every number here comes from
an AST walk over the 167 modules under `src/squadopt`, and the walk is described in the
verification section so a reviewer can disagree with the evidence rather than with the prose.

Companion documents: [dependency rules](dependency_rules.md) fixes the order this map
measures against, [ownership](ownership.md) says who may change what, and
[ADR 0001](decisions/0001-modular-monolith.md) records why the shape is one package rather
than several.

Re-measured against `587279a`. The `application` and `platform` packages arrived after the
first version of this document; their seam is in
[platform and runtime boundary](platform_runtime.md).

## Shape

One installed package, `squadopt`, built from `src/` by setuptools. Seventeen subpackages plus
one top-level module:

| Layer role | Packages |
| --- | --- |
| Source vocabulary | `data` (with `data/sources`) |
| Feature construction | `features` |
| Projection | `prediction` |
| Decision | `optimization`, `planning` |
| Scoring | `evaluation` |
| Spread and tails | `uncertainty`, `scenarios`, `risk` |
| Search and gates | `bayesopt`, `preflight`, `recalibration` |
| Measurement | `backtest`, `experiments` |
| Operations | `live` |
| Workflows | `application` |
| Runtime and registries | `platform` |
| Convenience wiring | `integration.py`, `squadopt/__init__.py` |

Outside the package: 77 files in `scripts/` and a `web/` frontend, which is not a Python
package and is therefore outside the import contract entirely — see
[platform and runtime boundary](platform_runtime.md).

`application` and `platform` now exist and sit at the top of the enforced order.
`application` holds the workflows the scripts used to inline — `run_gameweek_ops.py` lost 297
lines and `run_season_tick.py` 180 when they moved. `platform` holds run context, the manifest
contract and the artifact registry.

One package named in [dependency rules](dependency_rules.md) still does **not exist**:
`contracts`, the shared vocabulary that would end the reverse dependency below. It is named
there so the target is written down before anyone builds it.

## Measured import graph

Statement counts, not symbol counts. One `from squadopt.x import a, b, c` counts once.

| Package | Imports |
| --- | --- |
| `<root>` | `optimization` (3), `data` (1), `evaluation` (1) |
| `application` | `live` (10), `data` (9), `optimization` (1) |
| `backtest` | `features` (17), `prediction` (15), `evaluation` (6), `data` (4), `optimization` (4), `experiments` (2), `bayesopt` (1), `preflight` (1) |
| `bayesopt` | none |
| `data` | `optimization` (2) |
| `evaluation` | `optimization` (3) |
| `experiments` | `optimization` (13), `features` (10), `prediction` (10), `data` (8), `evaluation` (8), `backtest` (7), `bayesopt` (4), `scenarios` (3), `planning` (2), `preflight` (1) |
| `features` | `data` (6) |
| `live` | `data` (23), `prediction` (7), `optimization` (4), `planning` (4), `features` (2), `scenarios` (2) |
| `optimization` | none |
| `planning` | `optimization` (8) |
| `platform` | none |
| `prediction` | `features` (12), `data` (9), `optimization` (1) |
| `preflight` | `data` (2) |
| `recalibration` | `data` (4), `features` (2), `scenarios` (1) |
| `risk` | `optimization` (6), `uncertainty` (3), `evaluation` (1) |
| `scenarios` | `optimization` (10), `prediction` (3), `data` (2) |
| `uncertainty` | `data` (5), `evaluation` (3) |

Three readings worth keeping:

- **`optimization`, `bayesopt` and `platform` are leaves.** None imports any other
  subpackage. `optimization` is the solver core everything else composes; `bayesopt` is a
  search procedure that knows nothing about football; `platform` is deliberately ignorant of
  the engine, which is what makes it a runtime rather than a second core.
- **`live` is the widest consumer** (42 imports across 6 packages) and imports nothing that
  is not below it. The operational path is already layered correctly.
- **`risk` and `uncertainty` have almost no consumers inside the package** — only
  `risk` to `uncertainty`. They are reached from `scripts/` and `tests/`. That is an
  observation about how the spread work is used, not a defect.

## Where the dependencies still point the wrong way

Against the order fixed in [dependency rules](dependency_rules.md), **three package pairs
and five import statements** violate it:

| # | Edge | Imports | Sites | Closes with |
| --- | --- | --- | --- | --- |
| 1 | `data` to `optimization` | 2 | `data/schema.py:19`, `data/schema.py:20` | the `contracts` package |
| 2 | `prediction` to `optimization` | 1 | `prediction/integration.py:15` | the `contracts` package |
| 3 | `backtest` to `experiments` | 2 | `backtest/production_benchmark.py:57`, `:58` | moving `statistics` and `PromotionPolicy` into `evaluation` |

### 1 and 2 — the shared vocabulary is in the wrong place

`data/schema.py:19-20` reaches up into the solver for its own vocabulary:

```python
from squadopt.optimization.config import POSITIONS, Position
from squadopt.optimization.validation import REQUIRED_COLUMNS as PROJECTION_REQUIRED_COLUMNS
```

`Position` is defined at `optimization/config.py:12` as `Literal["GK", "DEF", "MID", "FWD"]`,
`POSITIONS` at `:13`, and `REQUIRED_COLUMNS` at `optimization/validation.py:15`. None of the
three is about optimization; all three are the words the whole system uses to describe a
player.

The module docstring at `data/schema.py:7-11` already says this vocabulary "arguably belongs
in a neutral module", and `../data_followups.md` section 11 proposes exactly that. This map
does not re-argue it — it records that the edge exists and that the fix is already agreed.

`prediction/integration.py:15` is the same problem wearing different clothes: it imports
`sort_players_by_id` from `optimization/coefficients.py:46`, a nine-line function whose own
docstring calls it "the stable player ordering used by the model and its fingerprints".
Canonical ordering is a contract, not a solver detail.

### 3 — the measurement cycle

`backtest/production_benchmark.py:57-58` imports `season_aware_moving_block_interval` and
`PromotionPolicy` from `experiments`, while seven `experiments` modules import `backtest`
(`control_residuals.py:20`, `multi_gw_rehearsal.py:30`, `policy_objective.py:26`,
`runner.py:12`, `scenario_policy_objective.py:27`, `season_chain.py:42`,
`selection_optimism.py:19`). That is a genuine cycle at package granularity.

It does not deadlock at import time, and the reason is worth writing down because it is
fragile rather than sound: `backtest/__init__.py` does not import `production_benchmark`, so
the `backtest` barrel finishes initialising before the reaching-back import ever runs. Adding
`production_benchmark` to that barrel would turn a latent cycle into an `ImportError`. Nobody
should have to discover this by trying it.

Both imported names are statistics and promotion policy — scoring concepts, not experiment
concepts. They belong in `evaluation`, which sits below both.

## What this map deliberately does not cover

- **Barrel width.** `experiments/__init__.py` re-exports 123 names, `live` 81, `data` 68. Wide
  barrels are a readability and coupling concern, not a layering one, and closing the three
  edges above does not require touching them. Recorded here, not scheduled.
- **`scripts/` and `tests/` inversions.** `src/` imports neither, so the useful direction of
  that arrow is preserved. But `tests/` imports `scripts/` at 24 sites, several reaching
  private members (for example `tests/unit/test_risk_reporting.py:5`, which imports three),
  and 77 entry-point modules are unchecked by two of the five gates. Ruff is **not** one of
  them: `ruff check .` and `ruff format --check .` both cover `scripts/`, and ruff's `src`
  setting governs first-party import resolution rather than which files are checked. The two
  that stop at the package boundary are mypy (`files = ["src/squadopt"]`) and `lint-imports`,
  which analyses exactly the 167 modules above. So the layering contract is unenforced in the
  directory that reaches across the most layers — a tooling gap for the core-architecture
  owner, not a package-layering gap. `pr_discipline.md` carried the same wrong attribution and
  is corrected separately.
- **`data/identity.py`** — resolved, and the resolution is the opposite of both options this
  entry offered. It now has an importer inside `src/squadopt`: `platform/fpl_capture.py`. It
  has none in `scripts/` at all, so the only remaining outside caller is
  `tests/unit/test_data_identity.py`. `platform` is the highest package layer and `data` the
  lowest, so that edge points downward and is legal by construction — the module is neither
  misplaced nor unused, and it took a consumer arriving rather than an argument to settle it.

## Verification

The test count comes from `pytest -q`. The import graph and both violation lists come from an
AST walk over `src/squadopt` that attributes each `import squadopt.*` and
`from squadopt.* import ...` statement to the subpackage containing the importing file, treats
`data/sources` as `data`, and reports any edge whose target sits at or above its source in the
order from [dependency rules](dependency_rules.md). Walking the AST rather than grepping text
matters: it counts imports inside `if TYPE_CHECKING:` blocks and function bodies, which a
grep over top-level lines would miss.

The three pairs and five statements above are the whole result. Anything else appearing means
this document is out of date, not that the walk is wrong.

Last measured against `95a6f7e`: **18 subpackages, 167 modules**, and the same three pairs and
five statements as at `587279a` (PR #144) and `b031ef1` — the same files and the same lines,
not merely the same count. The eighteenth subpackage is `api`, which became a package after
the previous measurement.

The baseline has now held across three measurements and every merge since #144, which is the
contract doing its job. The counts around it did not hold, which is why they are re-measured
here: the opening paragraph had said 132 modules while this line said 153, so the document
disagreed with itself about the size of the thing it was measuring.
