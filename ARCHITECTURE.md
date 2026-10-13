# Architecture

This document describes the shape of the SquadOpt system: what each part is for, which way
dependencies point, where each part runs, how the shape is enforced, and where the code does
not yet conform. It is the entry point for architectural questions. The decisions behind it are
recorded in the [architecture decision records](docs/architecture/decisions/README.md), and
[ADR 0010](docs/architecture/decisions/0010-clean-architecture-rings-and-repository-layout.md),
accepted by the owner on 2026-10-13, names the rings used below.

## 1. What the system is

SquadOpt turns captured Fantasy Premier League data into reproducible squad decisions and
publishes them as league-member views. It has two parts that share one code base:

- **The product**: the weekly capture, decision and publication run, the static member website,
  the in-browser device solver and the optional advice API with its workers.
- **The research arm**: the measurement laboratory that produces the committed records under
  `docs/`. It is part of the same installed package, but no product code may import it.

The installed Python code is one distribution, `football-squad-optimizer`, whose only import
package is `squadopt` under `src/`
([ADR 0001](docs/architecture/decisions/0001-modular-monolith.md),
[ADR 0008](docs/architecture/decisions/0008-structure-investment.md)); the Python under
`scripts/` and `tests/` sits outside it. The package is a layered modular monolith: one package,
a strict import order, and contracts that fail the build when a boundary is crossed. The
website, the Cloudflare Worker and the deployment files are separate deployables in the same
repository.

## 2. Rings

The packages are arranged in five rings, R1 (innermost) to R5 (outermost), following the
clean-architecture dependency rule: **a dependency points inward, never outward.** The research
arm is a side tree beside the product rings.

| Ring | Name | Holds | May import |
| --- | --- | --- | --- |
| R1 | Vocabulary | Types, contract versions, canonical ordering and schema validation shared by every ring | R1 packages below it in the layer order |
| R2 | Domain | The decision core (optimization, planning, scenarios, evaluation), the model lane (features, prediction) and the domain records of the live season | R1, and R2 packages below it in the layer order |
| R3 | Use cases | Application services that compose the domain into advice, publication, settlement and scoreboards | R1, R2, and R3 packages below it in the layer order |
| R4 | Adapters | Code that talks to the outside world: storage, captures, the file job queue, HTTP, model clients | R1 to R3, and R4 packages below it in the layer order |
| R5 | Composition and delivery | Entry points that wire adapters to use cases, and the deliverables outside the package: `scripts/`, `web/`, `workers/`, `deploy/`, `config/`, `.github/` | Any product ring |
| Research | Laboratory side tree | Measurement code behind the committed records | R1, R2, the storage half of `data`, and research packages below it in the layer order; no product ring may import it |

Every package directly under `src/squadopt`, and the one top-level module `integration.py`, has
one row below. A package that spans two rings names both, innermost first; the split is listed
under [known violations](#7-known-violations).

| Package | Ring | Role |
| --- | --- | --- |
| `contracts` | R1 | Shared vocabulary: positions, required projection columns and canonical player ordering, the factor grid, raw FPL point accounting, preferences, league list and league tree identity, honesty stems. Imports no other `squadopt` package. |
| `data` | R1, R4 | The canonical data layer. The schema and validation modules (`schema`, `errors`, `timestamps`, `identity`, `claim_identity`, `validation`, `cleaning`, `cohorts`, `fixtures`) are vocabulary; the storage and source modules (`snapshots`, `loaders`, `atomic`, `adapters`, `checksums`, `tables`, `pipeline`, `source_revision`, `_long_paths` and the `sources` subpackage) are adapters. |
| `features` | R2 | Leakage-safe feature engineering for the model lane. |
| `prediction` | R2 | Player projections and the optimizer-ready projection table. |
| `optimization` | R2 | Squad and lineup optimization with OR-Tools CP-SAT: the public driver `optimization.cpsat`, and the squad invariants and the tie-break shared through `optimization.decisions`. |
| `evaluation` | R2 | Scoring of prepared folds, the promotion policy and bootstrap statistics, shared by the product and the laboratory. |
| `scenarios` | R2 | Joint point scenarios, scenario paths, rival squads and fixed-decision scoring. |
| `planning` | R2 | Deterministic multi-gameweek transfer planning and chip timing. |
| `live` | R2 | Domain records of the live season: recommendation, ledger, tick, settlement, transfers and the per-member plan selection. It reads captured snapshots, never a live endpoint. |
| `integration` | R3 | One module, `integration.py`: a one-release re-export of `optimize_squad_from_csv` from `application.projection_csv`, removed in the release after the next `site-*` tag. |
| `application` | R3 | Use cases: typed advice, evidence, league and site publication, settlement, scoreboard and chip workflows, the strategy catalogue, and squad optimization from a canonical projection CSV (`projection_csv`, which the package root re-exports lazily). It imports no platform or script code. |
| `api` | R4, R5 | The FastAPI driving adapter, and the API process's composition (`squadopt.api.runtime:build_app`). It reaches the engine only through `platform` and `application`. |
| `platform` | R4, R5 | Driven adapters (file job queue and cache, captures, club-news model clients, storage, backup) and composition roots (the installed CLI, the weekly runner, the advice worker). |
| `experiments` | Research | The measurement programmes: designs, readings and reports behind the committed records. |
| `backtest` | Research | Leakage-safe walk-forward folds and benchmarks. |
| `bayesopt` | Research | Deterministic Bayesian policy search. |
| `recalibration` | Research | Calendar-aware residual measurement before recalibration. |
| `preflight` | Research | Validation of residual-export handoffs and of committed measurement records. Three operational commands load it on purpose (`LABORATORY_TOOLS` in `tests/architecture/test_run_boundary.py`). |

The rings are a reading of the enforced layer order, not a replacement for it. Read from the
bottom, the layer order in `pyproject.toml` reaches each product package only after every
package of an inner ring, and reaches the research arm only after every R2 package. Within a
ring the order is the tie-break ([dependency rules](docs/architecture/dependency_rules.md)).
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

Records stay at their paths: tests, runners and other records cite them, and some paths are
embedded in generated bytes, so ADR 0003 (rule 5) treats a move as a code change, with the tests
updated and the bytes regenerated.

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

Each seam is marked **implemented** when code and tests for it exist today, **in progress** when
an accepted record has placed its homes and its harness in the tree and the code behind them is
landing, or **boundary only** when the boundary is stated but the code behind it is not built.

| Seam | Status | What exists |
| --- | --- | --- |
| A stateless API and a pool of worker processes over a file job queue ([ADR 0006](docs/architecture/decisions/0006-backend-hosting.md)) | Implemented on one host | `FileJobQueue` and the answer cache in `platform`; workers scale by adding processes, because CP-SAT runs one search worker per solve. No multi-host deployment has been accepted. |
| The advice queue, cache and job specifications behind typed ports ([ADR 0005](docs/architecture/decisions/0005-persistence-boundaries.md)) | Implemented, file adapters only | `JobQueue`, `AdviceCacheRepository`, `AdviceJobSpecStore` and `PublishedViewStore` are Protocols in `platform`, each with a file adapter. |
| Captures, the ledger and handoffs behind ports | In progress (ADR 0011) | The homes exist and hold no module yet: `squadopt.application.ports` for the ports only the use cases consume, one module per group, and `squadopt.platform.storage` for the file adapters; `tests/architecture/test_storage_ports.py` holds each adapter to its port as the groups land. Use cases still read the storage modules of `data` directly (see known violations). |
| Device-first computation (issue #978) | Implemented for the one-week plan | The browser solves one-week plans, chips, rival strategies and the Top 100 weight with HiGHS; three- and five-week windows are still solved on the server. |
| More than one league, by `config/leagues.json` | Implemented in the weekly run | The capture and the weekly run take their leagues from the list (`league_list_v1`); the list names one league today, and the member page admits that league only. |
| Deterministic solver budgets | Implemented | CP-SAT runs with one search worker and a fixed seed (`configure_solver` in `optimization.cpsat`, the public driver). The advice, live and planning paths pass a deterministic time limit beside the wall-clock limit, so a search that its deterministic budget stops ends at a point fixed by its inputs. The wall clock can still stop a search first: `wall_clock_stopped_the_search` flags such a result as not reproducible, and the advice paths record the flag. |

## 6. Enforcement map

The import-linter contracts in `pyproject.toml` run as the fifth CI gate (`lint-imports`). Each
one has a row below. Only the last has `ignore_imports` entries: today's storage imports, held
under the ratchet rule of ADR 0010 (Decision 4), so the list can only shrink.

| Contract | What it holds |
| --- | --- |
| Layered architecture | The linear layer order; `exhaustive` makes every new package fail until it is placed. The laboratory sits above `live`, so an import of the laboratory from `live` or any package below it breaks this contract as well. |
| Product does not import the laboratory | No product package imports `experiments`, `backtest`, `bayesopt`, `recalibration` or `preflight`. |
| HTTP adapter uses only public boundaries | `api` reaches the engine only through `platform` and `application`. |
| Frameworks, network and databases stay in api and platform | Web frameworks, network clients, model SDKs, the standard library's network modules and `sqlite3` are imported only by `api` and `platform`. |
| The package never imports the repository scripts | Nothing under `src/squadopt` imports `scripts`. |
| The decision core imports no OS or process module | `contracts`, `optimization`, `planning`, `scenarios` and `evaluation` import no `os`, `shutil`, `tempfile` or `subprocess`. |
| The decision core imports no storage or source module | `contracts`, `optimization`, `planning`, `scenarios`, `evaluation` and `application.ports` (the home of the use-case storage ports, ADR 0011) import none of the storage and source modules of `data`: `snapshots`, `sources`, `atomic`, `loaders`, `adapters`, `checksums`, `tables`, `pipeline`, `source_revision` and `_long_paths`. `prediction` imports none of them either, and becomes a source when its zone owner agrees. |
| The CP-SAT solver stays in the decision core | Every package except `optimization`, `planning`, `scenarios`, `evaluation` and `backtest` is refused `ortools`; `backtest` imports it only to record its version. |
| Use cases and domain records import no process, thread, event-loop or command-line module | `application` and `live` import none of `subprocess`, `multiprocessing`, `concurrent`, `threading`, `signal`, `argparse` or `asyncio`; processes, threads and the command line belong to the composition roots. The contract sees direct imports only: one use case reaches `subprocess` through `data` (see known violations). |
| Use cases, domain records and features import no storage or source module | `application`, `live` and `features` import none of the storage and source modules of `data`, apart from today's 122 direct import edges from 43 modules, each an `ignore_imports` entry. A new edge fails the gate, and so does an entry whose edge is gone; `tests/architecture/test_storage_ratchet.py` holds the entries to a frozen copy that gives each its remedy and phase and pins its size by package, so the list only shrinks. |

The tests in `tests/architecture/` hold the rules that an import graph cannot see:

| Test | What it holds |
| --- | --- |
| `tests/architecture/test_architecture_rings.py` | The ring table above, the layer order, the laboratory contract and the run-boundary probe agree with one mapping, and every contract has a row in the map above. |
| `tests/architecture/test_storage_imports.py` | No source of the two storage contracts imports the `data` package root, which re-exports storage names, so the contracts see every `data` module those sources import. |
| `tests/architecture/test_storage_ratchet.py` | The `ignore_imports` entries of the storage ratchet are exactly a frozen baseline of today's direct storage imports, each with its remedy and phase; a new import, a new entry or an entry whose import is gone fails, and the size of the baseline is pinned by package. |
| `tests/architecture/test_core_file_io.py` | `contracts`, `optimization`, `planning`, `scenarios`, `evaluation` and `prediction` touch the file system only in 9 allowlisted functions of 3 modules; the allowlist only shrinks, and its size is pinned. The scan finds the `open` builtin, the file methods of `Path`, the pandas readers and writers it lists (a writer such as `to_csv` only when it is given a target), the file functions of `os`, `glob`, NumPy and joblib, also through an alias or an import by name, and any import of `shutil`, `tempfile` or `glob`. |
| `tests/architecture/test_use_case_file_io.py` | The same scan finds file access in `application`, `live` and `features` only in 33 allowlisted modules: 24 in `application`, 6 in `live` and 3 in `features`. The allowlist only shrinks, and its size is pinned by package. |
| `tests/architecture/test_contract_schema_paths.py` | Every path into `docs/contracts` comes from `contract_schema_path` in `squadopt.contracts.schema_paths` (ADR 0011, decision 6): the resolver answers the relative path the modules built before and refuses a name that is not `<name>_v<N>`; each `*_SCHEMA_PATH` constant is pinned to its former literal and names a file git tracks; no module under `src/squadopt` other than the resolver and the allowlisted `platform.history_documents` names the folder, and the allowlist only shrinks. |
| `tests/architecture/test_private_imports.py` | A single-underscore name is imported from another package under `src/squadopt` only by one of 20 allowlisted (importing module, imported module, name) entries, each with its remedy; the allowlist only shrinks, and no entry names a module of `optimization`. |
| `tests/architecture/test_run_boundary.py` | The product entry points and every operational command load no laboratory module when they run; a module of `application` whose name ends in `_experiment` is reported as laboratory, and `application` holds none. |
| `tests/architecture/test_platform_entry_points.py` | The operator surface ADR 0011 keeps while `platform` splits: the seven commands (`cli`, `weekly_operations`, `advice_worker`, `advice_load`, `backup_recovery`, `benchmark_capture`, `capture_measurement`) answer `--help` with exit 0 and their usage lines and expose `main` behind a `__main__` guard; the `squadopt` console script resolves to `squadopt.platform.cli:main`; the backend restart's import smoke passes in a fresh interpreter, `build_app` is a factory with no arguments and the launchers name it; `package_fingerprint()` hashes the whole package. |
| `tests/architecture/test_storage_ports.py` | The storage ports of ADR 0011 (decision 1): both homes, `application.ports` and `platform.storage`, are docstrings only with no barrel; every port and adapter module is registered; each registered adapter is a stateless frozen slots dataclass singleton annotated with its port, survives a pickle round trip, carries every port method with the same signature and answers a sample call as the `data` function it wraps does. The registry is empty until the first group lands. |
| `tests/architecture/test_layer_contracts.py` | Moved symbols keep their compatibility imports and their deterministic outputs. |
| `tests/architecture/test_documentation_paths.py` | A source path or command cited in the documentation exists. |
| `tests/architecture/test_markdown_links.py` | Every relative link in a tracked Markdown file resolves. |
| `tests/architecture/test_docs_reachable.py` | Every Markdown document under `docs/` is reached by a chain of relative links from the [documentation guide](docs/README.md), apart from the 192 unreachable on 2026-10-13, two frozen lists that only shrink and whose sizes are pinned. |
| `tests/architecture/test_docs_root.py` | No new living document is written directly under `docs/`: the 106 there on 2026-10-13 are a frozen list that only shrinks and whose size is pinned, and a new one goes in `architecture/`, `operations/`, `product/`, `research/` or `specs/`. |
| `tests/architecture/test_scripts_catalogue.py` | Every file under `scripts/` has exactly one row in the [script catalogue](scripts/README.md), every row outside its two retired sections names a file that is there, and a retired row names one that is gone. |
| `tests/architecture/test_package_maps.py` | The guide of each package that has one (`platform`, `application`, `experiments`, `live`, `data`, `prediction`, `features`) places every module of its package in exactly one family and names no module that is not there. |
| `tests/architecture/test_measurements_index.py` | Every committed record at the root of `docs/`, in `docs/architecture/` and in `docs/research/` has a row in the measurements index (ADR 0003, rule 1), found by a backticked name or a link target. |
| `tests/architecture/test_records_name_their_code.py` | A committed record at the root of `docs/` or in `docs/research/` names the commit that produced it; the exceptions, one frozen list per folder, only shrink, and their sizes are pinned. |
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
inside functions, the other rows by reading the cited files. Phase 1 is the change that added this
overview. Phase 2 is the deferred moves of ADR 0010 that this tree holds: on the owner's
direction of 2026-10-13 they were made together, without waiting for their triggers
([decisions record](docs/decisions.md)). Phase 3 is the moves that remain; each lands in its own
pull request once its trigger fires.

| Violation | Measured | Remedy | Phase |
| --- | --- | --- | --- |
| Use cases and domain records import the storage half of `data` | `application`: 89 import statements in 30 modules; `live`: 17 in 9; `features`: 16 in 4; together 122 direct import edges from 43 modules | Storage ports declared in `application`, with file adapters in `platform` | Phase 2: the ratchet is in force, the contract "Use cases, domain records and features import no storage or source module" with one `ignore_imports` entry per edge. Phase 3: the ports, under ADR 0011 (decision 1); the homes `application.ports` and `platform.storage` exist, and `tests/architecture/test_storage_ports.py` holds each adapter to its port as the groups land |
| Use cases, domain records and features read and write files themselves | The file-access scan of `tests/architecture/test_core_file_io.py`, which `tests/architecture/test_use_case_file_io.py` runs over these packages, finds file reads or writes in 24 modules of `application`, 6 of `live` (`ledger`, `recommendation`, `calibration`, `football_artifact`, `risk`, `tick`) and 3 of `features` (`evidence_artifact`, `rotation_evidence_artifact`, `settled_outcomes`) | File adapters in `platform` behind the storage ports of the first entry, so these packages receive and return records rather than paths | Phase 2: the ratchet is in force (`tests/architecture/test_use_case_file_io.py` allowlists the 33 modules, so no other module of these packages reads or writes a file; a new access inside a listed module is not seen). Phase 3: with the storage ports |
| `data` holds both R1 vocabulary and R4 storage, and sits at the bottom of the layer order | One package, two rings; `src/squadopt/data/__init__.py` imports `adapters`, `loaders`, `pipeline` and `snapshots`, so importing any `data` module loads those four at run time | The contract "The decision core imports no storage or source module" keeps the import statements of the packages that are clean today off the storage half, and `tests/architecture/test_storage_imports.py` refuses an import of the package root from them and from the sources of the storage ratchet; neither stops the run-time load | The contract and the test are in force (Phase 1); the split itself is an open question in ADR 0010 |
| Three vocabulary modules of `data` import its storage half | `claim_identity` imports `RosterPlayer` from `data.sources.club_news`, `cleaning` imports `PriceUnit` from `data.adapters`, and `cohorts` imports `LeagueStandingsPage` from `data.sources.fpl_live` | Move the three types into the vocabulary half, with a one-release re-export | With the split of `data`, an open question in ADR 0010; the data owner decides |
| `contracts` reads and writes files | `LEAGUE_LIST_FILE` and `read_league_list` in `src/squadopt/contracts/league_list.py`; `device_plan_sha256`, `read_league_directory`, `write_league_directory` and `legacy_tree_league_id` in `src/squadopt/contracts/league_tree.py` | Move the file IO to an adapter, with a one-release re-export | Phase 2: the ratchet is in force (`tests/architecture/test_core_file_io.py` allowlists the 5 functions). Phase 3: after issue #981 |
| The decision core reads files | `_manifest`, `_read_csv`, `_sha256` and `_file_sha256` in `src/squadopt/evaluation/component_handoff.py` read the Phase C manifest, its two tables and their bytes; a search of the rest of `optimization`, `planning`, `scenarios` and `evaluation`, and of `prediction`, finds no other file read or write | Move `read_phase_c_component_handoff` to an adapter, so `evaluation` receives the parsed tables | Phase 2: the ratchet is in force (`tests/architecture/test_core_file_io.py` allowlists the 4 functions). Phase 3: the move |
| A use case starts a process through `data` | `src/squadopt/application/advice_record.py` calls `source_revision()` in `src/squadopt/data/source_revision.py`, which runs `git` with `subprocess.run`; the process contract sees direct imports only | The composition root resolves the revision and passes it in, or a revision port with its adapter in `platform` | Phase 3, with the storage ports: the `revision` port of ADR 0011 (decision 1) |
| Runtime code names `docs/contracts` by a path relative to the working directory | 2 modules: `src/squadopt/contracts/schema_paths.py`, the one resolver of ADR 0011 (decision 6), from which 7 modules (2 in `application`, 5 in `platform`) take the default target of the function that writes their schema or the constant the tests read; and `src/squadopt/platform/history_documents.py`, whose `write_history_schema` still builds its path itself. None reads a schema when it runs ([contracts guide](docs/contracts/README.md)) | `history_documents` takes its path from the resolver once #969, which edits that module, has merged; anchoring the resolver's path to the repository root changes behaviour, so it is a separate decision for the owner | Phase 3: the resolver is in force, and `tests/architecture/test_contract_schema_paths.py` pins each constant to its former path, refuses the folder outside the resolver and holds `history_documents` on a shrink-only allowlist |
| Private names are imported across packages | 20 single-underscore names cross a package boundary under `src/squadopt`: 6 imported by the decision core (`planning/football_exact_lineup.py` takes 5 from `scenarios.expected_lineup`, `scenarios/expected_lineup.py` takes 1 from `evaluation.scoring`), 1 by `platform` (`weekly_operations.py` takes `_require_capture_name` from `application.weekly_plan`) and 13 by the laboratory (`experiments` reads `prediction.football`, `live.minute_evidence` and `evaluation.statistics`; `bayesopt` reads `contracts.factors`). The 19 names `planning` and `scenarios` took from the CP-SAT driver of `optimization.optimizer` are gone: the driver is public as `optimization.cpsat` (ADR 0011, decision 5), and each consumer binds the public names to the private names its tests patch | The owning module publishes the name and keeps the private alias for one release | Phase 3: the ratchet is in force (`tests/architecture/test_private_imports.py` allowlists the 20 and holds the list to a frozen copy of their keys, so no 21st appears); the 7 outside the laboratory leave under ADR 0011, and the laboratory's 13 stay on the allowlist |
| Ports are declared in an adapter ring | 15 of the 24 typed Protocols under `src/squadopt` are in `platform`: 8 are use-case ports of the advice backend (`AdviceCacheRepository`, `AdviceJobSpecStore`, `JobQueue`, `AdviceContextProvider`, `SwitchInputsProvider`, `LeagueDirectory`, `RateLimiter` and `PublishedViewStore`), consumed in `platform` and `api` and by no use case in `application`, and 7 are seams inside an adapter (`ApiDocument`, the Gemini `Transport` and `Reply`, `MessagesResource` and `CodingClient`, the OpenAI `Transport` and `RuntimeEventSink`); 3 are in `application` | The 8 use-case ports move to `application` with the read and submit use cases that consume them; the 7 seams stay in R4 by design | Phase 3, under ADR 0011 (decision 7), waiting on #988: the 8 move if #988 keeps the backend, and are deleted with it if #988 retires it |
| `platform` mixes deployment roles | 55 Python files: 54 in one flat package (weekly batch, API side, queue and worker, captures, club news, storage and CLI) and the package file of `storage/`, the first of ADR 0011's seven subpackages, which holds no adapter yet | Split by deployment unit (ADR 0008, M6) | Phase 3, under ADR 0011 (decision 3); `tests/architecture/test_platform_entry_points.py` pins the commands the split keeps |
| `scripts/` is outside the import contracts | mypy checks 7 script files; `lint-imports` checks none | Operator logic moves into the installed package, the direction ADR 0007 set | Phase 3 |

## 8. How to add

**A package under `src/squadopt`.** Choose its ring first. Add it to the layers list in
`pyproject.toml` (the contract is exhaustive, so an unplaced package fails), to the source or
forbidden lists of the contracts its ring implies, to the ring table above, to `RINGS` in
`tests/architecture/test_architecture_rings.py` and to the [package map](src/squadopt/README.md)
with its ring, layer and contract keys (the test fails until all three agree), and to
`.github/CODEOWNERS`. A new ring, or a package that fits none, needs an ADR.

**A module.** Put it in the package whose ring matches what it does, not where its first caller
lives. A module whose job is to talk to the outside world, such as a network client, a process
launcher or a store, is an adapter and belongs in `platform`, or in the storage half of `data`
for captured inputs. A module that only measures belongs in the research arm. When the package
has a guide, add the module's row to its family there in the same pull request;
`tests/architecture/test_package_maps.py` fails until the guide places it.

**A script.** Add one row to the [script catalogue](scripts/README.md) in the same pull request;
every file under `scripts/` has exactly one, which `tests/architecture/test_scripts_catalogue.py`
holds. An operational command imports product packages only;
`tests/architecture/test_run_boundary.py` imports every `.py` row of the operational table, apart
from the three laboratory tools it names, and fails if the laboratory loads. A measurement runner
writes its record to `docs/`, and the row it adds to the measurements index links the record's
Markdown twin: `tests/architecture/test_docs_reachable.py` follows links, not backticked names.

**A document.** Follow the naming key in the [documentation guide](docs/README.md). A record is
a JSON file and its Markdown twin with an index row that links the twin; a pre-registration ends
in `_prereg.md`, is linked from the [research guide](docs/research/README.md) or from its row in
the measurements index, and is frozen when it merges; anything else is a living document in the
folder of its audience (`docs/architecture`, `docs/operations`, `docs/product`, `docs/research`,
or `docs/specs` for a specification), never directly under `docs/`
(`tests/architecture/test_docs_root.py`). Link it from that folder's guide:
`tests/architecture/test_docs_reachable.py` fails on a document under `docs/` that no chain of
links from the documentation guide reaches.

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
- [Package map](src/squadopt/README.md), with the guides to
  [platform](src/squadopt/platform/README.md),
  [application](src/squadopt/application/README.md),
  [experiments](src/squadopt/experiments/README.md),
  [live](src/squadopt/live/README.md),
  [prediction](src/squadopt/prediction/README.md),
  [features](src/squadopt/features/README.md) and
  [data](src/squadopt/data/README.md)
- [Contracts guide](docs/contracts/README.md)
- [Script catalogue](scripts/README.md), [test guide](tests/README.md) and [web guide](web/README.md)
