# Architecture

This document describes the shape of the SquadOpt system: what each part is for, which way
dependencies point, where each part runs, how the shape is enforced, and where the code does
not yet conform. It is the entry point for architectural questions. The decisions behind it are
recorded in the [architecture decision records](docs/architecture/decisions/README.md), and
[ADR 0010](docs/architecture/decisions/0010-clean-architecture-rings-and-repository-layout.md)
names the rings used below.

## 1. What the system is

SquadOpt turns captured Fantasy Premier League data into reproducible squad decisions and
publishes them as league-member views. It has two parts that share one code base:

- **The product**: the weekly capture, decision and publication run, the static member website,
  the in-browser device solver and the optional advice API with its workers.
- **The research arm**: the measurement laboratory that produces the committed records under
  `docs/`. It is part of the same installed package, but no product code may import it.

All Python code is one installed distribution, `football-squad-optimizer`, whose only import
package is `squadopt` under `src/`
([ADR 0001](docs/architecture/decisions/0001-modular-monolith.md),
[ADR 0008](docs/architecture/decisions/0008-structure-investment.md)). It is a layered modular
monolith: one package, a strict import order, and contracts that fail the build when a boundary
is crossed. The website, the Cloudflare Worker and the deployment files are separate
deployables in the same repository.

## 2. Rings

The packages are arranged in five rings, R1 (innermost) to R5 (outermost), following the
clean-architecture dependency rule: **a dependency points inward, never outward.** The research
arm is a side tree beside the product rings.

| Ring | Name | Holds | May import |
| --- | --- | --- | --- |
| R1 | Vocabulary | Types, contract versions, canonical ordering and schema validation shared by every ring | R1 only |
| R2 | Domain | The decision core (optimization, planning, scenarios, evaluation), the model lane (features, prediction) and the domain records of the live season | R1 |
| R3 | Use cases | Application services that compose the domain into advice, publication, settlement and scoreboards | R1, R2 |
| R4 | Adapters | Code that talks to the outside world: storage, captures, the file job queue, HTTP, model clients | R1 to R3 |
| R5 | Composition and delivery | Entry points that wire adapters to use cases, and the deliverables outside the package: `scripts/`, `web/`, `workers/`, `deploy/`, `config/`, `.github/` | Any product ring |
| Research | Laboratory side tree | Measurement code behind the committed records | R1, R2 and the storage half of `data`; no product ring may import it |

Every package directly under `src/squadopt`, and the one top-level module `integration.py`, has
one row below. A package that spans two rings names both, innermost first; the split is listed
under [known violations](#7-known-violations).

| Package | Ring | Role |
| --- | --- | --- |
| `contracts` | R1 | Shared vocabulary: positions, required projection columns and canonical player ordering, the factor grid, raw FPL point accounting, preferences, league list and league tree identity, honesty stems. Imports no other `squadopt` package. |
| `data` | R1, R4 | The canonical data layer. The schema and validation modules (`schema`, `errors`, `timestamps`, `identity`, `claim_identity`, `validation`, `cleaning`, `cohorts`, `fixtures`) are vocabulary; the storage and source modules (`snapshots`, `loaders`, `atomic`, `adapters`, `checksums`, `tables`, `pipeline`, `source_revision`, `_long_paths` and the `sources` subpackage) are adapters. |
| `features` | R2 | Leakage-safe feature engineering for the model lane. |
| `prediction` | R2 | Player projections and the optimizer-ready projection table. |
| `optimization` | R2 | Squad and lineup optimization with OR-Tools CP-SAT, and the squad invariants shared through `optimization.decisions`. |
| `evaluation` | R2 | Scoring of prepared folds, the promotion policy and bootstrap statistics, shared by the product and the laboratory. |
| `scenarios` | R2 | Joint point scenarios, scenario paths, rival squads and fixed-decision scoring. |
| `planning` | R2 | Deterministic multi-gameweek transfer planning and chip timing. |
| `live` | R2 | Domain records of the live season: recommendation, ledger, tick, settlement, transfers and the per-member plan selection. It reads captured snapshots, never a live endpoint. |
| `integration` | R3 | One module, `integration.py`: optimizes a squad from a canonical projection CSV. The package root re-exports it lazily. |
| `application` | R3 | Use cases: typed advice, evidence, league and site publication, settlement, scoreboard and chip workflows, and the strategy catalogue. It imports no platform or script code. |
| `api` | R4, R5 | The FastAPI driving adapter, and the API process's composition (`squadopt.api.runtime:build_app`). It reaches the engine only through `platform` and `application`. |
| `platform` | R4, R5 | Driven adapters (file job queue and cache, captures, club-news model clients, storage, backup) and composition roots (the installed CLI, the weekly runner, the advice worker). |
| `experiments` | Research | The measurement programmes: designs, readings and reports behind the committed records. |
| `backtest` | Research | Leakage-safe walk-forward folds and benchmarks. |
| `bayesopt` | Research | Deterministic Bayesian policy search. |
| `recalibration` | Research | Calendar-aware residual measurement before recalibration. |
| `preflight` | Research | Validation of residual-export handoffs and of committed measurement records. Three operational commands load it on purpose (`LABORATORY_TOOLS` in `tests/architecture/test_run_boundary.py`). |

The rings are a reading of the enforced layer order, not a replacement for it. Read from the
bottom, the layer order in `pyproject.toml` reaches each product package only after every
package of an inner ring, with one exception, `integration` (see
[known violations](#7-known-violations)), and reaches the research arm only after every R2
package. Within a ring the order is the tie-break
([dependency rules](docs/architecture/dependency_rules.md)).
`tests/architecture/test_architecture_rings.py` holds this table, the layer order, the
laboratory contract and the run-boundary probe to one mapping.

## 3. The research arm and the three tiers

The laboratory (`experiments`, `backtest`, `bayesopt`, `recalibration`, `preflight`) measures
candidate models and policies. Its runners live in `scripts/` and write records to `docs/`.
Installing it activates nothing. The [roadmap](docs/product/roadmap.md) states which models
and policies members receive, and the [measurements index](docs/measurements_index.md) registers
what each committed record found.

[ADR 0003](docs/architecture/decisions/0003-measurement-artifacts.md) sorts every generated file
into one of three tiers by what it is for:

| Tier | Home | Committed | Examples |
| --- | --- | --- | --- |
| Record | `docs/` | Yes, with a row in the measurements index | A JSON record and its Markdown twin |
| Evidence | `artifacts/` | No | The per-fold or per-scenario expansion behind a record |
| Operational state | `data/` | No; backed up separately | Captures, the season ledger, projection handoffs |

Records never move: tests, runners and other records cite their paths, and some paths are
embedded in generated bytes.

## 4. Deployment units

| Unit | Code | Entry point | State | Where it runs today |
| --- | --- | --- | --- | --- |
| Member website | `web/` | `npm run build`; the `Deploy Pages` workflow deploys a tagged `site` artifact | Reads the published views in `web/public/data` | Cloudflare Pages, at `squadopt.mymandev.com` ([ADR 0004](docs/architecture/decisions/0004-cloudflare-pages-deployment.md)) |
| Device solver | `web/src/features/league/device/` | A Web Worker (`deviceSolver.worker.ts`) running HiGHS compiled to WebAssembly | Reads the published device-plan table ([`league_device_plan_v1`](docs/contracts/league_device_plan_v1.md)) | The member's browser |
| Weekly run | `squadopt.platform.weekly_operations` | `python -m squadopt.platform.weekly_operations` | Writes `data/snapshots`, `data/handoffs`, `data/ledger`, `data/advice_records` and `data/runtime/weekly`; publishes `web/public/data` through a pull request | The owner's Windows PC, run by the owner ([decisions of 2026-10-07](docs/decisions.md)) |
| Installed CLI | `squadopt.platform.cli` | The `squadopt` console script (`squadopt.platform.cli:main`) | Writes run manifests and logs under `data/runtime` and `data/logs` | The operator's machine |
| Advice API | `squadopt.api` | `uvicorn --factory squadopt.api.runtime:build_app` | Reads the published tree, snapshots, handoffs and the answer cache; writes jobs to the shared store | The owner's PC, behind the `squadopt-api` Cloudflare Tunnel ([backend free hosting](docs/backend_free_hosting.md)) |
| Advice worker | `squadopt.platform.advice_worker` | `python -m squadopt.platform.advice_worker` | Claims jobs from the shared store and writes the answer cache | The owner's PC, several processes beside the API |
| FPL probe | `workers/fpl-probe/` | The `Deploy FPL probe` workflow, dispatched by hand | A Workers KV namespace | Cloudflare Workers, only while deployed ([FPL forwarder probe](docs/fpl_forwarder_probe.md)) |
| Backend uptime check | `.github/workflows/backend-uptime.yml` | A schedule every 15 minutes | Opens and closes `backend-down` issues | GitHub Actions |

[ADR 0006](docs/architecture/decisions/0006-backend-hosting.md) decides that the API and the
worker are one container image run as two processes (`deploy/compose.yaml`).
[ADR 0009](docs/architecture/decisions/0009-advice-backend-hosting-options.md) compares other
hosts and is proposed, not decided. Issue #988 decides whether the backend moves off the
owner's PC or is retired in favour of the device solver.

## 5. Scaling seams

Each seam is marked **implemented** when code and tests for it exist today, or **boundary
only** when the boundary is stated but the code behind it is not built.

| Seam | Status | What exists |
| --- | --- | --- |
| A stateless API and a pool of worker processes over a file job queue ([ADR 0006](docs/architecture/decisions/0006-backend-hosting.md)) | Implemented on one host | `FileJobQueue` and the answer cache in `platform`; workers scale by adding processes, because CP-SAT runs one search worker per solve. No multi-host deployment has been accepted. |
| The advice queue, cache and job specifications behind typed ports ([ADR 0005](docs/architecture/decisions/0005-persistence-boundaries.md)) | Implemented, file adapters only | `JobQueue`, `AdviceCacheRepository`, `AdviceJobSpecStore` and `PublishedViewStore` are Protocols in `platform`, each with a file adapter. |
| Captures, the ledger and handoffs behind ports | Boundary only | Use cases read the storage modules of `data` directly (see known violations). |
| Device-first computation (issue #978) | Implemented for the one-week plan | The browser solves one-week plans, chips, rival strategies and the Top 100 weight with HiGHS; three- and five-week windows are still solved on the server. |
| More than one league, by `config/leagues.json` | Implemented in the weekly run | The capture and the weekly run take their leagues from the list (`league_list_v1`); the list names one league today, and the member page admits that league only. |
| Deterministic solver budgets | Implemented | CP-SAT runs with one search worker and a fixed seed (`optimization.optimizer`), and the advice, live and planning paths pass a deterministic time limit, so where a search stops does not depend on machine load. |

## 6. Enforcement map

The import-linter contracts in `pyproject.toml` run as the fifth CI gate (`lint-imports`). Each
one has a row below, and none has an `ignore_imports` entry.

| Contract | What it holds |
| --- | --- |
| Layered architecture | The linear layer order; `exhaustive` makes every new package fail until it is placed. The laboratory sits above `live`, so an import of the laboratory from `live` or any package below it breaks this contract as well. |
| Product does not import the laboratory | No product package imports `experiments`, `backtest`, `bayesopt`, `recalibration` or `preflight`. |
| HTTP adapter uses only public boundaries | `api` reaches the engine only through `platform` and `application`. |
| Frameworks, network and databases stay in api and platform | Web frameworks, network clients, model SDKs, the standard library's network modules and `sqlite3` are imported only by `api` and `platform`. |
| The package never imports the repository scripts | Nothing under `src/squadopt` imports `scripts`. |
| The decision core imports no OS or process module | `contracts`, `optimization`, `planning`, `scenarios` and `evaluation` import no `os`, `shutil`, `tempfile` or `subprocess`. |
| The decision core and prediction import no storage or source module | `contracts`, `optimization`, `planning`, `scenarios`, `evaluation` and `prediction` import none of the storage and source modules of `data`: `snapshots`, `sources`, `atomic`, `loaders`, `adapters`, `checksums`, `tables`, `pipeline`, `source_revision` and `_long_paths`. |
| The CP-SAT solver stays in the decision core | Every package except `optimization`, `planning`, `scenarios`, `evaluation` and `backtest` is refused `ortools`; `backtest` imports it only to record its version. |
| Use cases and domain records start no processes or threads | `application` and `live` import none of `subprocess`, `multiprocessing`, `concurrent`, `threading`, `signal`, `argparse` or `asyncio`; processes, threads and the command line belong to the composition roots. |

The tests in `tests/architecture/` hold the rules that an import graph cannot see:

| Test | What it holds |
| --- | --- |
| `tests/architecture/test_architecture_rings.py` | The ring table above, the layer order, the laboratory contract and the run-boundary probe agree with one mapping, and every contract has a row in the map above. |
| `tests/architecture/test_run_boundary.py` | The product entry points and every operational command load no laboratory module when they run; a module of `application` whose name ends in `_experiment` is reported as laboratory. |
| `tests/architecture/test_layer_contracts.py` | Moved symbols keep their compatibility imports and their deterministic outputs. |
| `tests/architecture/test_documentation_paths.py` | A source path or command cited in the documentation exists. |
| `tests/architecture/test_markdown_links.py` | Every relative link in a tracked Markdown file resolves. |
| `tests/architecture/test_measurements_index.py` | Every committed record has a row in the measurements index (ADR 0003, rule 1). |
| `tests/architecture/test_records_name_their_code.py` | A committed record names the commit that produced it; the exceptions only shrink. |
| `tests/architecture/test_mypy_file_set_is_described.py` | The scripts the type gate checks are the ones the PR discipline names. |
| `tests/architecture/test_dependency_pins.py` | Every declared dependency is pinned inside its declared range. |
| `tests/architecture/test_operations_docs_match_the_workflows.py` | The operations documents name the variables and steps the workflows use. |
| `tests/architecture/test_roadmap_current_position.py` | The roadmap's current position agrees with the records it cites. |

The website holds its own layer rules with the TypeScript compiler: `web/src/architecture.test.ts`
keeps the lower zones (`design`, `lib`, `i18n`, `data`) free of `features` and `app` imports and
forbids import cycles, and `web/src/architecture.features.test.ts` forbids dependency loops
between features. The [web guide](web/README.md) maps the zones to the rings.

## 7. Known violations

Each entry was measured on this tree: the import counts with an AST scan that includes imports
inside functions, the other rows by reading the cited files.

| Violation | Measured | Remedy | Phase |
| --- | --- | --- | --- |
| Use cases and domain records import the storage half of `data` | `application`: 88 import statements in 29 modules; `live`: 17 in 9; `features`: 16 in 4 | Storage ports declared in `application`, with file adapters in `platform` | Phase 2: a shrink-only ratchet. Phase 3: the ports, triggered by ADR 0005 or issue #1010 |
| `data` holds both R1 vocabulary and R4 storage, and sits at the bottom of the layer order | One package, two rings | The contract "The decision core and prediction import no storage or source module" keeps the packages that are clean today off the storage half | The contract is in force (Phase 1); the split itself is an open question in ADR 0010 |
| `contracts` reads and writes files | `LEAGUE_LIST_FILE` and `read_league_list` in `src/squadopt/contracts/league_list.py`; `read_league_directory` and `write_league_directory` in `src/squadopt/contracts/league_tree.py` | Move the file IO to an adapter, with a one-release re-export | Phase 2: ratchet; Phase 3: after issue #981 |
| Runtime code loads schemas from `docs/contracts` by a relative path | 7 modules: 2 in `application`, 5 in `platform` | A ratchet that allowlists the 7 modules, so that no eighth appears | Phase 2 |
| The CP-SAT driver has no public port | 19 private names imported from `optimization.optimizer`: 5 by `planning/optimizer.py`, 7 by `scenarios/optimization.py`, 7 by `scenarios/rank.py` | A public solver driver in `optimization` | Phase 3 |
| Ports are declared in an adapter ring | 15 of the 24 typed Protocols under `src/squadopt` are in `platform`; 3 are in `application` | Use-case ports move to `application` | Phase 3 |
| Laboratory modules live in the use-case ring | Six `football_*_experiment` modules in `application`, imported only by tests; the run-boundary probe reports them as laboratory if a product entry point loads one | Move them to `experiments`, with no re-export | Phase 2, after agreement on issue #1012 |
| `platform` mixes deployment roles | 54 Python files in one flat package: weekly batch, API side, queue and worker, captures, club news, storage and CLI | Split by deployment unit (ADR 0008, M6) | Phase 3, needs a new ADR |
| `integration` is a use-case module placed as its own layer | `src/squadopt/integration.py` sits between `evaluation` and `optimization` in the layer order | Fold it into `application`, with a one-release re-export | Phase 2 |
| `scripts/` is outside the import contracts | mypy checks 7 script files; `lint-imports` checks none | Operator logic moves into the installed package, the direction ADR 0007 set | Phase 3 |

## 8. How to add

**A package under `src/squadopt`.** Choose its ring first. Add it to the layers list in
`pyproject.toml` (the contract is exhaustive, so an unplaced package fails), to the source or
forbidden lists of the contracts its ring implies, to the ring table above and to `RINGS` in
`tests/architecture/test_architecture_rings.py` (the test fails until both name it), and to
`.github/CODEOWNERS`. A new ring, or a package that fits none, needs an ADR.

**A module.** Put it in the package whose ring matches what it does, not where its first caller
lives. A module whose job is to talk to the outside world, such as a network client, a process
launcher or a store, is an adapter and belongs in `platform`, or in the storage half of `data`
for captured inputs. A module that only measures belongs in the research arm.

**A script.** Add one row to the [script catalogue](scripts/README.md) in the same pull request.
An operational command imports product packages only; `tests/architecture/test_run_boundary.py`
imports every row of the operational table and fails if the laboratory loads. A measurement
runner writes its record to `docs/` and adds the row to the measurements index.

**A document.** Follow the naming key in the [documentation guide](docs/README.md). A record is
a JSON file and its Markdown twin with an index row; a pre-registration ends in `_prereg.md` and
is frozen when it merges; anything else is a living document in the folder of its audience.

**A deployable.** A new process, Worker or hosted service needs a row in the deployment units
table, its configuration under `deploy/` or its own folder, and an ADR when it changes where
state lives.

## 9. Links

- [Repository map](README.md) and [contributing](CONTRIBUTING.md)
- [Documentation guide](docs/README.md) and [glossary](docs/glossary.md)
- [Architecture agreements](docs/architecture/README.md), including the
  [dependency rules](docs/architecture/dependency_rules.md),
  [system map](docs/architecture/system_map.md) and [ownership](docs/architecture/ownership.md)
- [Architecture decision records](docs/architecture/decisions/README.md)
- [Script catalogue](scripts/README.md), [test guide](tests/README.md) and [web guide](web/README.md)
