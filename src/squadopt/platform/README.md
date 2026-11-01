# `squadopt.platform`

The outer ring of the package (R4 adapters and R5 composition,
[ARCHITECTURE.md](../../../ARCHITECTURE.md)): the code that talks to the outside world and the
entry points that wire it to the use cases in `squadopt.application`. It is the one package,
with `squadopt.api`, that may import web frameworks, network clients, model SDKs and `sqlite3`
(the contract "Frameworks, network and databases stay in api and platform"). No package below
it in the layer order imports it, and it imports no laboratory module.

Its 66 Python files serve several deployment units: 50 implementation modules and 4
aliases at old paths in the flat folder, the package file, and the seven subpackages of ADR
0011, of which `storage/` holds the four shared durable-state modules and the six others their
package file only.
[ADR 0011](../../../docs/architecture/decisions/0011-storage-ports-and-platform-split.md)
splits the package into seven subpackages by deployment unit in Phase 3 and keeps every
command as it is; the first unit pull request moved the shared durable-state modules into
`storage/`, which holds no adapter yet. Until the other moves land this page is the map: every
module is in exactly one family below.

Review: either owner approves a change here; the `club_news_*` modules are İbrahim's zone
([ownership](../../../docs/architecture/ownership.md)).

## Which process loads which family

| Process | Entry point | Families it uses |
| --- | --- | --- |
| Weekly run | `python -m squadopt.platform.weekly_operations` | Weekly run, captures, run records |
| Weekly schedule | `python -m squadopt.platform.weekly_schedule`, every 15 minutes from the host's scheduler | Weekly run (it starts the weekly run), `fpl_capture`, club news |
| Advice API | `uvicorn --factory squadopt.api.runtime:build_app` | Advice API services, built by `backend_runtime` |
| Advice worker | `python -m squadopt.platform.advice_worker` | Advice queue and workers, with the services `backend_runtime` builds |
| Installed CLI | the `squadopt` console script (`squadopt.platform.cli:main`) | Installed CLI, run records, `fpl_capture` |
| Club news capture | `python -m scripts.capture_club_news` | Club news and the model adapter |

Before the moves, `tests/architecture/test_platform_entry_points.py` pins the operator surface
ADR 0011 keeps: the `--help` usage lines and `main` of the seven `python -m` commands (`cli`,
`weekly_operations`, `advice_worker`, `advice_load`, `backup_recovery`, `benchmark_capture`,
`capture_measurement`) and of the scheduled gate of #1243, `weekly_schedule`, the console
script's target, the backend restart's import smoke,
`build_app` as a factory with no arguments, and the tree `package_fingerprint()` hashes.

## Weekly run

The installed weekly entry point, the gate that starts it on a schedule, its durable journal,
the member publication service and the optional football inputs it seals.

| Module | What it does |
| --- | --- |
| `weekly_operations.py` | The installed weekly entry point: typed application services run as stages of a durable journal. |
| `weekly_schedule.py` | The scheduled gate (#1243): a morning run once a UTC day and a final run a lead before each deadline, each started at most once, with its club news, on any host. |
| `weekly_journal.py` | Durable sequential stage execution: ownership lock, input and output fingerprints, resume. |
| `weekly_publish.py` | Publishes one gameweek's site view: worktree, copy, commit, push and pull request in one command. |
| `publication_workers.py` | Process scheduling for the member publication service. |
| `native_windows.py` | Isolated native HiGHS process port for three/five-week server plans, its version probe for the weekly preflight, and the operator's per-window solver summary; avoids the OR-Tools library collision on Linux. |
| `football_bundle.py` | Validates existing football inputs and publishes one immutable ready marker last. |
| `football_minute_basis.py` | Dispatches composite companions with captured roster, deadline and calendar bindings, while retaining legacy fixture-basis reading (`src/squadopt/platform/football_minute_basis.py:88`). |
| `football_publication.py` | Validates and publishes capture-bound football documents without fitting a model. |
| `history_documents.py` | The public shape of recorded weekly history (`weekly_suggestion_history_v1`), without computing a score. |

## Advice API services

What the API process serves, and the composition root that wires the backend's parts.

| Module | What it does |
| --- | --- |
| `backend_runtime.py` | The composition root: the one place the backend's parts are wired to each other, for the API and the worker. |
| `advice_read.py` | The read side of on-demand advice: league state and pure cache lookups. |
| `advice_submit.py` | The write side: one request becomes a job record, with rate and open-job limits. |
| `advice_documents.py` | The public read contracts: what the advice route and the league route may serve. |
| `api_contract.py` | Transport-neutral request and response contracts of the HTTP API (`backend_api_v1`). |
| `queries.py` | The query seam for published application views. |
| `capture_context.py` | The backend's view of one capture: everything an advice computation needs. |
| `advice_switches.py` | The per-capture inputs behind a request's switches, and how they enter an advice address. |
| `contributions.py` | Moderated community observations, stored in SQLite; never a prediction or solver input. |

## Advice queue and workers

The file job queue, the worker loop and what keeps them observable and recoverable.

| Module | What it does |
| --- | --- |
| `advice_worker.py` | The worker process: what one job means, and the loop that keeps claiming jobs. |
| `advice_queue.py` | Worker orchestration and compatibility imports for the advice queue. |
| `file_advice_queue.py` | The recoverable file queue, with fenced, short metadata transactions. |
| `queue_contracts.py` | Adapter-neutral queue operations and attempt ownership errors. |
| `jobs_contract.py` | The job lifecycle contract, `backend_jobs_v1`. |
| `advice_job_spec.py` | What a queued job is for, stored beside the queue rather than inside it. |
| `advice_cache.py` | The immutable-key answer cache behind a protocol, and the cache key. |
| `_damaged_entry.py` | Moves aside bytes at a create-once address that do not parse, rather than answering from them. |
| `worker_heartbeat.py` | Each worker reports that it is alive, and readiness asks whether any worker is. |
| `worker_metrics.py` | A worker-owned Prometheus listener; no counters are shared with the API process. |
| `advice_observability.py` | Structured log lines, counters and readiness for the advice backend. |
| `advice_load.py` | A bounded HTTP capacity probe of an explicitly selected advice deployment. |

## Captures

Network adapters that write immutable, checksummed captures; everything downstream reads the
captured bytes, not a live endpoint.

| Module | What it does |
| --- | --- |
| `fpl_capture.py` | One immutable FPL deadline capture. |
| `cohort_capture.py` | Captures the official overall elite cohort before a gameweek deadline. |
| `elite_capture.py` | Captures a frozen elite cohort's previous-gameweek picks before the deadline. |
| `official_injury_capture.py` | A bounded capture of the official league injury widget, without a model call. |
| `benchmark_capture.py` | Private weekly Benchmark V2 receipts, kept apart from published decisions. |
| `capture_measurement.py` | Offline availability calibration and a paired late-capture audit; changes no projection. |

## Club news and the model adapter

The only code that calls a language model, and the club pages it reads. Which provider codes a
week's news is configuration, not an import.

| Module | What it does |
| --- | --- |
| `club_news_acquire.py` | Acquires one week's club news and names the capture it wrote. |
| `club_news_coverage.py` | Describes a completed acquisition without treating silence as coverage. |
| `club_news_fetch.py` | The network adapter for one club's own pages, and the refusals that come before a request. |
| `club_news_provider.py` | Chooses the model that codes a week's news from configuration. |
| `club_news_settings.py` | Private club-news settings; parsing them imports no client and opens no connection. |
| `club_news_model.py` | Codes club news with the Anthropic SDK client, and states what a coding call refuses to do. |
| `club_news_gemini.py` | Codes club news with a hosted Gemini model over one REST call, with no vendor SDK. |
| `club_news_openai.py` | Codes club news through OpenAI or a compatible Chat Completions endpoint. |

## Run records and recovery

Provenance for every installed run, and the offline backup of private state.

| Module | What it does |
| --- | --- |
| `runtime.py` | The shared lifecycle of an application operation: manifest, input and output lineage, structured events, a typed result. |
| `context.py` | The identity and reproducibility inputs of one run (`RunContext`). |
| `manifest.py` | Deterministic `run_manifest_v1` serialization. |
| `artifacts.py` | Immutable artifact records and a file-backed provenance registry (`artifact_record_v1`). |
| `runlog.py` | Structured run logging for the live path. |

## Storage adapters

The file adapters behind the storage ports of ADR 0011 (decision 1), one module per port group:
each exports a stateless frozen slots dataclass singleton annotated with its port, calls the
`data` functions unchanged or holds code moved verbatim, and is wired into the use cases by the
composition roots (`weekly_operations.py`, `cli.py`, `publication_workers.py` and the scripts).
`tests/architecture/test_storage_ports.py` holds each adapter to its port. The subpackage holds
no adapter yet: each group lands in its own pull request. It already holds the shared
durable-state primitives every unit above it uses (ADR 0011, decision 3): the queue lock, the
store probe, handoff retention and the backup command.

| Module | What it does |
| --- | --- |
| `storage/__init__.py` | The package file, a docstring that names the adapter groups and the rule each adapter follows. |
| `storage/_queue_lock.py` | Short metadata transactions under an OS lock that is released when its process dies; also used by `weekly_journal` and `benchmark_capture`. |
| `storage/store_probe.py` | Proves that the shared store provides what the adapters rely on before the backend serves. |
| `storage/projection_retention.py` | Retains a handoff's exact bytes by capture before the gameweek alias is published. |
| `storage/backup_recovery.py` | Offline, checksummed copies of explicitly selected private roots; `python -m squadopt.platform.backup_recovery` reaches it through the permanent alias. |

## Deployment units

The seven subpackages of ADR 0011 (decision 3), one layer each in the contract "Platform
deployment units import only the shared adapters below them": `operations` and `backend` at
the top, then `football`, `club_news`, `capture`, `runs` and `storage`. Six hold their package
file only until their modules move, one pull request per unit.

| Module | What it does |
| --- | --- |
| `runs/__init__.py` | Run identity, provenance and the stage journal; empty until its modules move. |
| `capture/__init__.py` | FPL network captures; empty until its modules move. |
| `club_news/__init__.py` | Club pages, the official injury capture and the model clients; empty until its modules move. |
| `football/__init__.py` | Football input artifacts; empty until its modules move. |
| `backend/__init__.py` | The API and worker cluster; empty until its modules move. |
| `operations/__init__.py` | The CLI, the weekly run and the publication workers; empty until its modules move. |

## Aliases at the old paths

The moves above leave a file at each old path (ADR 0011, decision 8): three one-release
`sys.modules` aliases, each the moved module itself under its old name, which go in the first
pull request after the next `site-*` release, and one permanent entry alias. `tests/architecture/test_platform_layout.py` holds each alias to the
moved object and refuses a new importer of an old path.

| Module | What it does |
| --- | --- |
| `_queue_lock.py` | One-release alias of `storage/_queue_lock.py`. |
| `store_probe.py` | One-release alias of `storage/store_probe.py`. |
| `projection_retention.py` | One-release alias of `storage/projection_retention.py`. |
| `backup_recovery.py` | Permanent entry alias: `python -m squadopt.platform.backup_recovery` runs `storage/backup_recovery.py`'s `main`. |

## Installed CLI and package surface

| Module | What it does |
| --- | --- |
| `cli.py` | The installed command line, `squadopt`: gameweek decide, roll and settle, and the season tick. |
| `__init__.py` | Re-exports the transport-neutral contracts: run context, manifest, artifact registry, API contract, published-view queries and the runtime runner. |

## Ports declared here

15 of the 24 typed `Protocol` classes under `src/squadopt` are declared in this package. The
first eight rows are the use-case ports of the advice backend. A port that a use case needs
belongs in `squadopt.application` (R3): these eight move there with the read and submit use
cases that consume them if #988 keeps the backend, and are deleted with it if #988 retires it
([ADR 0011](../../../docs/architecture/decisions/0011-storage-ports-and-platform-split.md),
decision 7). The other seven are seams inside an adapter and stay here by design.

| Port | Module | What it stands for | Adapter in the repository |
| --- | --- | --- | --- |
| `JobQueue` | `queue_contracts.py` | The advice job queue | `FileJobQueue` in `file_advice_queue.py` |
| `AdviceCacheRepository` | `advice_cache.py` | The immutable answer cache | `FileAdviceCache` in the same module |
| `AdviceJobSpecStore` | `advice_job_spec.py` | Stored job specifications | `FileAdviceJobSpecStore` in the same module |
| `PublishedViewStore` | `queries.py` | Reads of the published view tree | `FilePublishedViewStore` in `squadopt/api/views.py` |
| `AdviceContextProvider` | `advice_read.py` | The current capture context, or none while not ready | `CaptureContextProvider` in `backend_runtime.py` |
| `SwitchInputsProvider` | `advice_read.py` | The inputs a context offers a request's switches | `CaptureContextProvider` in `backend_runtime.py` |
| `LeagueDirectory` | `advice_read.py` | The connected leagues the read side may know | `FileLeagueDirectory` in the same module |
| `RateLimiter` | `advice_submit.py` | Per-client request limits | `FixedWindowRateLimiter` in the same module |
| `ApiDocument` | `api_contract.py` | An API document that serializes to JSON | The request, response, error and service-info documents of the same module |
| `RuntimeEventSink` | `runtime.py` | A run's structured events | `RunLog` in `runlog.py` |
| `Transport`, `Reply` | `club_news_gemini.py` | One HTTP call to the Gemini API and its reply | `_BoundedTransport` and `_BoundedReply` in the same module |
| `MessagesResource`, `CodingClient` | `club_news_model.py` | The Anthropic SDK's messages resource and client | The SDK's own client, or a test's recorder |
| `Transport` | `club_news_openai.py` | One HTTP call to a Chat Completions endpoint | `_HttpxTransport` in the same module |

## Runtime paths to `docs/contracts`

Five modules here take the path of a schema under `docs/contracts` from `contract_schema_path`
in `squadopt.contracts.schema_paths`, the one resolver of ADR 0011 (decision 6), which answers
the same path relative to the working directory each built before: `api_contract.py`,
`artifacts.py` and `manifest.py` as the default target of the function that writes the
committed schema, and `advice_documents.py` and `jobs_contract.py` as constants the tests read.
`history_documents.py` still builds its path itself in `write_history_schema`, and takes it from
the resolver once #969, which edits that module, has merged. No module reads a schema from that
folder: the validators that run are built from the schema functions in code.
`tests/architecture/test_contract_schema_paths.py` pins each constant to its former literal,
holds `history_documents.py` on a shrink-only allowlist, and fails when any other module under
`src/squadopt` names the folder. The [contracts guide](../../../docs/contracts/README.md) lists
every schema with its producer.
