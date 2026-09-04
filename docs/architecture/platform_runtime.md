# Platform and Runtime Boundary

How the research engine becomes an executable platform without HTTP, persistence, job
queues, authentication, or deployment concerns leaking into the engine. This document fixes
the boundary; implementation PRs consume it rather than re-deciding it. The package begins
with transport-neutral run contracts and grows only through those reviewed PRs.

Companion documents: [dependency rules](dependency_rules.md) define the full package order,
[ownership](ownership.md) assigns review authority, and
[ADR 0001](decisions/0001-modular-monolith.md) keeps the system inside one layered package.

## Objective

The platform/backend role owns this transition:

```text
research engine
    -> reproducible runtime
    -> backend platform
    -> multi-user product
```

It does not own the scientific contents of prediction models, optimization objectives,
uncertainty methods, scenario generation, or evaluation gates. Those components publish
contracts; the platform records, invokes, persists, and serves them.

## The boundary

The dependency direction is one way:

```text
CLI / HTTP API / workers / schedulers
                  |
                  v
          runtime / platform
                  |
                  v
             application
                  |
                  v
            research engine
```

The intended future package order is therefore:

```text
... -> live -> application -> platform -> entry points
```

`entry points` means the installed CLI, HTTP API, workers, schedulers, and the remaining
script shells. They may compose platform services. No package below `platform` may import
`platform`, and no package below an entry point may import an entry point.

Infrastructure dependencies stop at the platform boundary:

- `application` and the research engine do not import FastAPI, Pydantic transport models,
  PostgreSQL drivers, Redis clients, queue clients, authentication libraries, telemetry
  exporters, or deployment SDKs;
- platform adapters may import those libraries and translate their values into application
  contracts;
- HTTP handlers, CLI commands, and workers contain no prediction, solver, planning, or
  evaluation logic;
- persistence stores application/runtime state and provenance; it does not become a second
  implementation of the ledger, optimizer, or experiment rules.

## The application seam today

`squadopt.application` exposes transport-neutral `DecideRequest`, `SettleRequest`, and
`TickRequest` commands with typed results, alongside the `ui_view_v1` read models and the
deterministic static JSON tree consumed by the web frontend. Decision verification and the
capture/decide/settle lifecycle therefore have one implementation shared by script shells and
future CLI, HTTP, and worker adapters. Network capture remains an injected entry-point
dependency; the application package does not perform HTTP transport itself.

The platform consumes this implementation; it does not rewrite it. In particular:

1. A runtime adapter calls a public application contract.
2. If that contract does not exist, the application owner adds the smallest transport-neutral
   service in a separate application PR.
3. The platform PR then adapts that service to a run registry, CLI, API, worker, or scheduler.
4. Platform code never reaches into private functions under `scripts/` to avoid the missing
   application seam.

Changes to an application contract consumed by the platform need both the core-architecture
owner and the platform/backend owner. Implementation details behind an unchanged contract
remain with the application owner until the handover recorded in
[ownership](ownership.md) takes place.

## Platform modules and their responsibilities

The names below describe boundaries, not a commitment to create every module at once.
Each arrives through its own reviewed PR when the preceding contract exists.

### Runtime context and run registry

Every serious execution receives one identity and records at least:

- `run_id`, lifecycle status, and timestamps;
- repository commit;
- input and configuration fingerprints;
- prediction, uncertainty, scenario, optimizer, and planner identities where applicable;
- deterministic seed and runtime budget;
- output artifact identities and terminal failure, if any.

The initial `run_context_v1` contract records the operational run id and creation time together
with the repository commit, configuration fingerprint, named input fingerprints, component
versions, and deterministic seed. Its composite reproducibility fingerprint deliberately
excludes the run id and creation time, so retries remain distinct attempts with the same
reproducibility identity. `run_manifest_v1` is the strict, deterministic JSON envelope for
that context; lifecycle status, budgets, outputs, and failures arrive with the run repository.

The existing season-tick JSONL log is an event stream, not this registry. The registry links
the whole execution and its artifacts; logging records what happened during it.

### Artifact registry and lineage

The platform registers an artifact's identity, producing run, kind, location, checksum,
schema version, and creation time. It records the direction:

```text
input artifacts -> run -> output artifacts
```

`artifact_record_v1` is the portable record for that edge. `FileArtifactRegistry` stores one
immutable JSON document per artifact under `records/<artifact_id>.json`; the artifact bytes
remain under a separately configured artifact root. Stored locations are canonical POSIX paths
relative to that root, never machine-specific absolute paths. The artifact id deterministically
binds the run id, input/output role, kind, location, SHA-256 checksum, and schema version.

Registration reads the raw bytes, computes their checksum, and is idempotent for an exact retry.
Reusing the same run/role/kind/location slot with different bytes or a different schema is
refused. `get_artifact()` validates record structure and identity, `verify_checksum()` re-reads
the registered file before replay or consumption, and `lineage()` returns deterministically
ordered input and output edges for a run. Record publication is atomic and never overwrites an
existing identity.

Existing snapshot, ledger, residual-export, measurement, and UI-view checksums remain their
domain contracts. The registry references and verifies them; it does not replace their
validation with a weaker generic check.

### Runtime orchestration

A common runner surrounds an application call with lifecycle and provenance:

1. validate the runtime request;
2. resolve exact input artifacts and promoted component versions;
3. create and start the run;
4. invoke the application service;
5. register outputs;
6. complete or fail the run with a structured result.

CLI, API, workers, and schedulers call this runner. They do not each implement their own
version of the workflow.

`RuntimeRequest` binds a validated operation name, `RunContext`, and declared input files.
Every `RuntimeInputArtifact` names exactly one `RunContext.input_fingerprints` entry; the
request must resolve the complete mapping and preflight verifies each file checksum against
that declared digest before any run state is published.
An entry point adapts a public application service to a zero-argument callable returning a
`RuntimeOperationResult`: its transport-neutral application value plus declared output files.
This keeps application request types below the platform boundary and keeps private `scripts/`
functions out of the runtime.

`RuntimeRunner` preflights every input inside the artifact root before publishing run state,
writes the immutable manifest, registers input lineage, invokes the application operation, and
registers its output lineage. Application and output-registration exceptions become a typed
failed `RuntimeResult` with the failing phase, error type, message, timestamps, and elapsed
runtime. Input or manifest preparation failures are raised because the application operation
has not started. Interrupts and other `BaseException` values are never converted into ordinary
failures.

The optional `RuntimeEventSink` is structurally implemented by the existing live `RunLog`.
The runner refuses a sink whose `run_id` differs from `RunContext.run_id`, then emits
`runtime.started`, `runtime.completed`, or `runtime.failed`. A manifest, artifact lineage, and
structured event stream therefore identify the same execution. The terminal result remains a
returned contract until a later run repository persists lifecycle state; the JSONL stream is
still not treated as that repository.

### Installed CLI

The package installs one `squadopt` entry point with three operational commands:

```console
squadopt gameweek decide
squadopt gameweek settle --gameweek NN
squadopt season tick
```

The CLI contains parsing, path resolution, console rendering, and exit-code translation only.
It calls the public application services through `RuntimeRunner`; it does not import private
functions from `scripts/`. Relative paths are resolved beneath `--workspace-root` (the current
directory by default), and every registered path must remain inside that portable artifact
boundary. Recorded locations always use POSIX separators even on Windows.

Each invocation writes its canonical command request beneath `data/runtime/requests`, a
`run_manifest_v1` beneath `data/runtime/runs`, and input/output lineage beneath
`data/runtime/registry`. The same run id is used for `data/logs/<operation>/*.jsonl`.
`--repository-commit` and `SQUADOPT_REPOSITORY_COMMIT` support installed environments without
a Git checkout; otherwise the CLI resolves `git rev-parse HEAD` without a shell. Exit 0 means
completed, 1 is a stated domain/preparation failure, and 2 is an unexpected runtime failure.

The old `scripts.run_gameweek_ops`, `scripts.run_season_tick`, and manual capture module remain
thin compatibility shells for one release. They delegate to this CLI or the public platform
capture adapter and are not alternate implementations.

A tick that contacts the live FPL endpoint registers the newly captured response as an output,
not as a pre-existing reproducibility input: a changing external response cannot honestly be
replayed before it has been captured. Any decision made after that step consumes the immutable,
checksummed snapshot. Replay guarantees therefore begin at the captured bytes, while the first
network read remains traceable but inherently external.

### Persistence

The first implementation is file-backed so the contract is exercised before a database schema
freezes it. The current runner still names that concrete adapter; a database implementation
must first extract the narrow repository behavior it already consumes. PostgreSQL then holds
transactional application state and query metadata, while large historical, residual,
scenario, and model artifacts remain Parquet/object-storage concerns. The schema, publication
order, and migration triggers are fixed in
[ADR 0005](decisions/0005-persistence-boundaries.md).

Core and application code never contain SQL. Concrete persistence adapters live at or above
the platform boundary.

### Service and compute adapters

FastAPI, background jobs, cache, authentication, deployment, and observability are later
adapters over a stable runtime. Their order matters:

The versioned routes, normalized commands, read-model reuse, idempotency semantics, and public
errors are fixed in the [backend HTTP boundary](backend.md) before a framework is installed.

- no HTTP implementation before request/response and runtime contracts;
- no queue implementation before the job lifecycle contract;
- no Redis implementation before execution fingerprints and cache policy;
- no authentication before a user domain exists;
- no object storage or GPU orchestration before a measured workload requires it.

## Reproducibility guarantee

The platform aims to make this statement testable:

```text
same repository commit
+ same input artifact fingerprints
+ same configuration fingerprints
+ same component versions
+ same deterministic seed
= same recorded decision
```

This guarantee composes the determinism already owned by the engine. The platform must not
claim reproducibility when an underlying component declares a numerical or environmental
limit; that limit belongs in the run manifest and user-facing result.

## Promotion authority

The platform records and enforces promotion; it does not decide scientific merit.

- Data/predictive modeling declares prediction candidates and their evidence.
- Optimization/decision science declares decision candidates and gate readings.
- The required owners approve or reject the promotion under the existing process.
- Platform/runtime records the immutable decision and resolves only explicitly promoted
  versions for production executions.

A passing benchmark does not update a production registry automatically. Promotion is an
explicit, reviewable state change backed by the gate artifacts and sign-offs.

## Review and change rules

1. One topic per PR. A run contract, file repository, CLI adapter, database adapter, and API
   endpoint are separate changes.
2. File-backed behavior comes before PostgreSQL, queue, cache, or cloud adapters unless a
   measured requirement proves otherwise.
3. A platform PR may consume a public application API but does not refactor its implementation.
4. A missing application seam is closed in its own application PR before the platform adapter.
5. A new dependency crossing this boundary changes this document and the import-linter order
   before code is merged.
6. Live-path ownership and the deadline freeze remain governed by
   [ownership](ownership.md); introducing a runtime wrapper does not transfer the live path
   early.

## First delivery sequence

The first three feature PRs are deliberately storage- and transport-neutral. Each groups the
small contracts needed for one reviewable outcome instead of opening a PR per class or file:

1. `feature/run-context-manifest` — run identity, reproducibility fingerprints, manifest
   serialization, and tests;
2. `feature/artifact-registry` — artifact records, a file-backed registry, checksum
   verification, lineage, and tests;
3. `feature/runtime-orchestration` — the shared execution lifecycle around public application
   services and its integration tests.

The runtime contracts were followed by `feature/application-command-services`, which supplied
the public decide, settle, and tick seams, and then `feature/unified-cli`, which exercised all
four preceding deliveries through an installed command. The independent persistence decision
is now [ADR 0005](decisions/0005-persistence-boundaries.md), and
`feature/backend-api-contract` fixes the HTTP boundary and `backend_api_v1` documents before a
framework is installed. PostgreSQL, FastAPI implementation, workers, Redis, authentication,
and scaling remain later stages rather than implicit contents of these contract PRs.
