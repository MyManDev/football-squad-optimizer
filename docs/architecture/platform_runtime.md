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

`squadopt.application` exists. Its current public surface turns frozen live records into
`ui_view_v1` view models and writes the deterministic static JSON tree consumed by the web
frontend. It is the first application-layer pilot, not yet a complete service API for every
operation.

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

### Persistence

Repository protocols separate runtime behavior from storage. The first implementation is
file-backed so the contract is exercised before a database schema freezes it. PostgreSQL may
later hold application state and metadata; large historical, residual, scenario, and model
artifacts remain file/Parquet or object-storage concerns.

Core and application code never contain SQL. Concrete persistence adapters live at or above
the platform boundary.

### Service and compute adapters

FastAPI, background jobs, cache, authentication, deployment, and observability are later
adapters over a stable runtime. Their order matters:

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

After those contracts are exercised, the next independent deliveries are
`feature/unified-cli`, `docs/persistence-adr`, and `feature/backend-api-contract`. PostgreSQL,
FastAPI implementation, workers, Redis, authentication, deployment, and scaling are later
stages, not implicit contents of the first platform PR.
