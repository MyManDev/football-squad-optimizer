# Dependency Rules

The one-directional order every import inside `squadopt` must respect, the exceptions that
exist today, and the rule for changing either. This document is the contract that
`lint-imports` enforces in CI and review.

For what the graph actually looks like right now, see [system map](system_map.md). For why
the shape is a single layered package, see [ADR 0001](decisions/0001-modular-monolith.md).
For the boundary above the application layer, see
[platform and runtime boundary](platform_runtime.md).

## The order

A package may import any **lower-level** package, never a higher-level one. The diagram
lists the levels from lowest to highest; dependencies point toward `contracts`.

```
contracts
  data
    features
      prediction
        optimization
          evaluation
            scenarios
              planning
                live
                  bayesopt
                    preflight
                      recalibration
                        backtest
                          experiments
                            application
                              integration
                                platform
                                  api / entry points
```

`integration` is one module, `src/squadopt/integration.py`. The use case it held, optimizing
a squad from a canonical projection CSV, lives in `src/squadopt/application/projection_csv.py`
since 2026-10-13, and `integration.py` re-exports `optimize_squad_from_csv` from there for one
release (rule 2 below). It imports only `application`, so it sits directly above `application`
as a layer of its own, and the layer goes with the module in the release after the next
`site-*` tag.

`application`, `platform`, and the optional `api` adapter now exist and are enforced as the
highest package layers in `pyproject.toml`, with only the one-release `integration` layer
between `application` and `platform`. `contracts` is the lowest package and
imports no other `squadopt` layer; `application` may reach everything below it; and `platform` may consume
application contracts without allowing HTTP, persistence, queue, authentication, or
deployment concerns to flow back into them. `api` is the concrete FastAPI entry point and may
consume `platform` and `application` public contracts. Other entry points mean CLI, workers,
schedulers, and script shells; that remains an architectural role rather than one proposed
package.

The general layers contract permits a high layer to import any lower layer. The API has a
second, stricter contract: `squadopt.api` may reach engine packages only indirectly through
the public `platform` and `application` boundaries. A new direct API import from `live`,
`optimization`, `prediction`, `planning`, `scenarios`, or any other engine package fails
`lint-imports`.

### Why this order and not the obvious one

The first draft of this order grouped the packages by what they are about, which reads better
and does not work. Three groupings had to be broken, each because the code already says
otherwise:

| Tempting grouping | Why it fails |
| --- | --- |
| `evaluation` above `uncertainty`/`scenarios`/`risk` | `uncertainty` imports `EvaluationFold` three times (`adaptive.py:16`, `calibration.py:16`, `fixture_folds.py:17`) and `risk` once (`evaluation.py:9`). Scoring a fold is more primitive than describing its spread, so `evaluation` goes below. |
| `{uncertainty, scenarios, risk}` as one tier | `risk` imports `uncertainty` three times (`config.py:13`, `evaluation.py:29`, `optimizer.py:20`). Risk is built on top of spread, not beside it. |
| `{experiments, bayesopt, recalibration, preflight}` as one tier | Four separate edges cross it: `experiments` to `bayesopt` (4), `backtest` to `bayesopt` (1), `backtest` to `preflight` (1), `experiments` to `preflight` (1). `bayesopt` is in fact a pure leaf and `preflight` only imports `data`, so both belong far lower. |

The `uncertainty` and `risk` packages in the first two rows have been removed with their runners
(2026-10-12); the rows stay as the reasoning that set the order.

The original ordering change took the violation count from **16
imports across 9 pairs** to **5 imports across 3 pairs** without moving a single line of code.
The shared-contract and evaluation extraction subsequently removed those five exceptions.

### Where the order is genuinely free

Some packages are independent of each other and their relative position is arbitrary. Do not
read meaning into it, and do not "fix" it. One constraint has held over all of them since the
rings were named ([ADR 0010](decisions/0010-clean-architecture-rings-and-repository-layout.md),
accepted): every laboratory package sits above every R2 package, and so above `live`, and
`tests/architecture/test_architecture_rings.py` fails otherwise. What stays free is the order of
the laboratory packages among themselves, subject to their imports:

- `bayesopt` imports only `contracts`.
- `preflight` imports only `data`.
- `recalibration` imports `data`, `features` and `scenarios`.
- `planning` imports `optimization`, `contracts` (`DecisionPreferences` from
  `contracts.preferences`, in `planning/chip_strategy.py:6` and `planning/optimizer.py:15`)
  and `scenarios`: three modules import `scenarios.expected_lineup`
  (`planning/expected_swap.py:31`, `planning/football_exact_lineup.py:17` and
  `planning/lineup_utility.py:21`). So `planning` must sit above `scenarios` and below `live`
  and `experiments`, which import it; the ring rule above also places it below `bayesopt`,
  `preflight`, `recalibration` and `backtest`.

If a future import makes one of these positions load-bearing, say so here at the same time.

Each line above is read from the import graph, not remembered. This prints the `squadopt`
packages that one package imports directly (here `planning`; `grimp` is the graph library
`import-linter` installs). Run it for the names in the list before changing it, and where a
line here and the output disagree, the output is right:

```console
python -c "import sys, grimp; p = sys.argv[1]; g = grimp.build_graph('squadopt'); m = {'squadopt.' + p} | g.find_descendants('squadopt.' + p); print(sorted({i.split('.')[1] for x in m for i in g.find_modules_directly_imported_by(x) if i.startswith('squadopt.')} - {p}))" planning
```

## No baseline exceptions

The layers contract contains **zero `ignore_imports` entries**. The five former exceptions
are resolved by these shared owners:

| Former edge | Shared owner | Compatibility imports |
| --- | --- | --- |
| `data.schema` to `optimization.config` / `optimization.validation` | `contracts.players`: `Position`, `POSITIONS`, `REQUIRED_COLUMNS` | Original optimization locations and `data.schema` still expose the same objects. |
| `prediction.integration` to `optimization.coefficients` | `contracts.players.sort_players_by_id` | `optimization.coefficients.sort_players_by_id` re-exports the same function. |
| `backtest.production_benchmark` to `experiments` / `experiments.config` | `evaluation.promotion.PromotionPolicy` and `evaluation.statistics` | None since 2026-09-26: the one-release re-exports in `experiments.config` and `experiments.statistics` are removed; the `experiments` barrel still lists the policy, the errors and the interval as part of its interface. |
| `application.mode_selection` to `experiments.plan_selection` | `live.plan_selection` (the product's per-member plan chooser, `mode_plan_selection_v1`); its `ExperimentExecutionError` joins its siblings in `evaluation.promotion` | None at the old location: when it moved, `experiments` sat below `live`, so a re-export there would have inverted the layers contract (rule 1 outranks rule 2). The laboratory callers (`scripts/measure_mode_plan_selection.py`, `tests/unit/test_plan_selection.py`) import `squadopt.live.plan_selection` directly (moved 2026-09-10); the error is imported from `evaluation.promotion`, where the `experiments` barrel also takes it from. |

The policy's two exception base classes also live in `evaluation.promotion`, keeping their
existing `ExperimentError` / `ExperimentConfigurationError` names and inheritance so callers
can keep catching the old experiment imports. `ExperimentExecutionError` joined them there
when `plan_selection` moved to `live`. Candidate/design types, comparisons and factorial
effects remain in `experiments`.

The extraction changes no policy defaults, normalization, error messages, seed derivation,
resampling order, percentile arithmetic, canonical player ordering or fingerprint payload.
Compatibility tests pin pre-extraction sequences and fingerprints. Historical measurement
artifacts are not rewritten. Narrowing the existing public barrels is separate work.

### What goes in `contracts`

Only vocabulary. Nothing that computes a decision, and nothing that imports anything else in
`squadopt`.

- `Position` and `POSITIONS` in `contracts/players.py`
- `REQUIRED_COLUMNS` in the same module, the projection contract
- `sort_players_by_id` in the same module — nine lines whose docstring calls
  it "the stable player ordering used by the model and its fingerprints"; canonical ordering
  is a contract even though it is a function
- `BayesianFactor` and `FactorKind` in `contracts/factors.py`: the bounded-knob grid a
  strategy declares and DoE/BO read. It is vocabulary two layers share (the product's
  strategy catalogue and the laboratory), which is why it lives here and not in
  `bayesopt`; the one-release re-export in `bayesopt.models` was removed on 2026-09-26.
- `PointCoefficients`, `ComponentMoments`, `RawPointResult`, `raw_points` and
  `clip_points` in `contracts/football_point_accounting.py`: the raw FPL point algebra
  that the football prediction families and the live native integration both score with
  (#1070). It imports nothing else in `squadopt` and turns caller-supplied moments into
  expected points, not a decision. Both owners placed it here on 2026-10-10 (#1071).
- `CONTRACT_SCHEMA_DIRECTORY` and `contract_schema_path` in `contracts/schema_paths.py`: the
  one place that names the folder of the committed schemas, `docs/contracts`, relative to the
  working directory as every schema writer and test used it before
  ([ADR 0011](decisions/0011-storage-ports-and-platform-split.md), decision 6). It imports
  nothing else in `squadopt` and refuses a name that is not `<name>_v<N>`.
- Identity and fingerprint primitives and the contract-version registry remain future
  candidates under [ADR 0002](decisions/0002-contract-versioning.md); they are not moved by
  this extraction.

`contracts` is a shared boundary in [ownership](ownership.md): changes need both owners (all
three until the team change of 2026-09-25).
That is deliberate friction. A module every layer depends on is the one place where a casual
edit is most expensive, and it is the natural dumping ground for anything that is awkward to
place. If a symbol is not vocabulary that at least two layers need, it does not go here.

## Rules for changing this document

1. **The baseline may only shrink.** A PR that adds a violating import is rejected, not
   baselined. If the import is genuinely necessary, the order is wrong and this document
   changes first, in its own PR, with both owners agreeing.
2. **Re-exports live exactly one release.** When a symbol moves, the old location keeps
   re-exporting it so no import breaks in the same PR that moves it. The re-export is removed
   in a later, separate PR. This is what makes each migration step reviewable in isolation.
3. **Boundary files change only by joint approval** — see [ownership](ownership.md).
4. **The order is a claim about the code, so it is verified, not trusted.** Any change here
   comes with the regenerated numbers.
5. **A private name is not an import surface.** A single-underscore name is imported across
   packages only where `tests/architecture/test_private_imports.py` allowlists it, with its
   remedy, and that list only shrinks: the owning module publishes the name and keeps the
   private alias for one release (rule 2), as `optimization.cpsat` did for the CP-SAT driver
   that `planning` and `scenarios` had reached through the private names of
   `optimization.optimizer` ([ADR 0011](decisions/0011-storage-ports-and-platform-split.md),
   decision 5).

## Verification

CI runs `lint-imports` against the contract in `pyproject.toml`. `import-linter` lists layers
**highest first**, which is the reverse of the order written at the top of this document. Its
current top is:

```toml
[tool.importlinter]
root_package = "squadopt"

[[tool.importlinter.contracts]]
name = "Layered architecture"
type = "layers"
containers = ["squadopt"]
exhaustive = true
layers = [
    "api",
    "platform",
    "integration",
    "application",
    "experiments",
    "backtest",
    "recalibration",
    "preflight",
    "bayesopt",
    "live",
    "planning",
    "scenarios",
    "evaluation",
    "optimization",
    "prediction",
    "features",
    "data",
    "contracts",
]
```

The excerpt leaves out the comments and the other settings of `pyproject.toml`, which is the
executable source of truth. Because the layers are named inside the `squadopt` container and
the contract is exhaustive, a new package directly under `squadopt` fails the gate until it is
placed in this list. `squadopt.api` is listed above `squadopt.platform`, which is listed
above `squadopt.application`; the API therefore cannot be imported back into runtime or
application code. The platform's first package contract is the versioned run context and
manifest. The layers contract has no baseline violation and no `ignore_imports` entry. Every
new upward dependency fails the same contract.

A separate forbidden-import contract lists `squadopt.api` as its source, every engine package
below `application` as forbidden, and permits indirect imports. That last setting is
deliberate: application services may compose the engine, while HTTP modules may not bypass
those services.

The original five-edge baseline was measured against `b031ef1` (PR #110). The shared-layer
extraction verifies the zero-exception contract with `lint-imports`; behavior compatibility
is covered by `tests/architecture/test_layer_contracts.py` and the existing consumer suites.

`lint-imports` runs every contract in `pyproject.toml`. Only the tenth has `ignore_imports`
entries, and they may only shrink (rule 1 above):

1. `Layered architecture`: the order at the top of this document.
2. `Product does not import the laboratory`: see [the groups the order encodes](#the-groups-the-order-encodes).
3. `HTTP adapter uses only public boundaries`: the forbidden contract above.
4. `Frameworks, network and databases stay in api and platform`: web frameworks, network
   clients, model SDKs and `sqlite3` stay in `api` and `platform`.
5. `The package never imports the repository scripts`: nothing under `src/squadopt` imports
   `scripts`.
6. `The decision core imports no OS or process module`: `contracts`, `optimization`,
   `planning`, `scenarios` and `evaluation` import no `os`, `shutil`, `tempfile` or
   `subprocess`.
7. `The decision core imports no storage or source module`: the same five packages, and
   `application.ports`, the home ADR 0011 gives the use-case storage ports, import none of the
   storage and source modules of `data`.
8. `The CP-SAT solver stays in the decision core`: only `optimization`, `planning`,
   `scenarios`, `evaluation` and `backtest` may import `ortools`.
9. `Use cases and domain records import no process, thread, event-loop or command-line module`:
   `application` and `live` import no process, thread, signal, command-line or event-loop
   module directly.
10. `Use cases, domain records and features import no storage or source module`:
    `application`, `live` and `features` import none of the storage and source modules of
    `data` beyond the 122 direct import edges from 43 modules they have today, each an
    `ignore_imports` entry; `tests/architecture/test_storage_ratchet.py` holds the entries to
    a frozen copy whose size it pins by package, so the list only shrinks.
11. `Platform deployment units import only the shared adapters below them`: inside `platform`,
    the seven subpackages of ADR 0011 (decision 3) are layers, `operations` and `backend` at
    the top, then `football`, `club_news`, `capture`, `runs` and `storage`; the flat modules
    that have not moved yet are ignored by name, and
    `tests/architecture/test_platform_layout.py` holds that list to exactly the flat modules.

The seventh to the tenth enforce the rings that
[ADR 0010](decisions/0010-clean-architecture-rings-and-repository-layout.md), an accepted record,
names. The tenth is a ratchet under that record's ratchet rule (Decision 4): its allowlist
holds exactly the storage imports of 2026-10-13, each with its remedy and phase, and a new
one fails the gate. The eleventh enforces the platform split of
[ADR 0011](decisions/0011-storage-ports-and-platform-split.md), decision 3, one unit at a time.
The [architecture overview](../../ARCHITECTURE.md) gives what each contract holds in its
enforcement map, and `tests/architecture/test_architecture_rings.py` checks that every contract in
`pyproject.toml` is named in this list and has a row in that map.

## The groups the order encodes

The linear order above is one valid extension of a smaller structure. Read by role, the
packages fall into five groups, each importing only groups below it:

| Group | Packages |
| --- | --- |
| adapters | `api` |
| runtime | `platform` |
| use cases | `application`, `integration` |
| domain | `live`, `planning`, `optimization`, `evaluation`, `scenarios`, `prediction`, `features` |
| data | `data`, `contracts` |

The measurement **laboratory** (`experiments`, `backtest`, `bayesopt`, `recalibration`,
`preflight`) is a side tree, not a group in that column. It may import domain and data, and no
product group (adapters, runtime, use cases, or domain) may import it. The linear order alone
could not say this: it placed the laboratory below `application`, so the deployed advice worker
was loading 43 laboratory modules, and a product decision (`plan_selection`) was living in the
lab. The contract `Product does not import the laboratory` in `pyproject.toml` states the rule
directly, and the layers contract stays as the tie-break within each group. Since the rings were
named (ADR 0010, accepted), the layer order also places the laboratory above `live`, so for
`live` and every package below it the layers contract refuses an import of the laboratory as
well; for `application`, `platform` and `api` the forbidden contract alone refuses it.

That contract started with eight `ignore_imports` entries, all in `application`, each annotated
with the follow-up PR that removed it. The last (`mode_selection` to `experiments.plan_selection`)
left with the `plan_selection` move to `live`, and the list is gone: like the layers contract, it
carries **zero** `ignore_imports` entries, and a new violation fails the gate.

`risk` and `uncertainty` joined the forbidden list on 2026-09-15, and they joined it while it
cost nothing. Measured at the time: outside its own package **nothing** under `src/` imports
`risk`, and `uncertainty` is imported only by `risk/config.py`, `risk/evaluation.py`,
`risk/optimizer.py` and `experiments/shadow_calibration.py`. Both are research surfaces the
contract had classified as product, so the gate would have allowed a product import of either
and said nothing. Adding them changed no import and left all three contracts green. The reason
to do it early is the one the eight `ignore_imports` entries recorded: a boundary is cheap to
state while nothing crosses it, and expensive once nine statements do. Both packages have since
been removed with their runners (2026-10-12), and their entries left the contracts with them.

## Rings

[ADR 0010](decisions/0010-clean-architecture-rings-and-repository-layout.md), an accepted record,
names the rings these groups map to, and the [architecture overview](../../ARCHITECTURE.md)
gives the ring of every package, the contracts that enforce them and the known violations. The
groups above correspond as follows: `contracts` and the schema half of `data` are R1
(vocabulary); the domain group is R2; the use cases group is R3; `api`, `platform` and the
storage half of `data` are R4 (adapters) and, for their entry points, R5 (composition). The
laboratory is the research side tree. Naming the rings changed one thing in the order: the
laboratory now sits above `live`. Folding `integration` into `application` later moved the
`integration` layer from above `optimization` to above `application`. The layers contract
remains the executable statement and the tie-break within a ring, and
`tests/architecture/test_architecture_rings.py` checks that the order reads the rings from the
inside out, with no exception.