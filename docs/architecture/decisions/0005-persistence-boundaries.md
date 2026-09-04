# ADR 0005 — Separate transactional metadata from analytical artifacts

- **Status:** accepted
- **Date:** 2026-08-20
- **Decider:** platform owner
- **Related:** [ADR 0003](0003-measurement-artifacts.md),
  [platform and runtime boundary](../platform_runtime.md),
  [`run_manifest_v1`](../../contracts/run_manifest_v1.schema.json),
  [`artifact_record_v1`](../../contracts/artifact_record_v1.schema.json)

## Context

The first platform runtime is intentionally file-backed. A CLI invocation writes a canonical
request, immutable run manifest, artifact records, and structured JSONL events under
`data/runtime` and `data/logs`. Captures, ledgers, handoffs, experiment evidence, and published
views also have existing file contracts. This gives one-machine execution strong provenance
without committing to infrastructure before the behavior is understood.

The backend will introduce different workloads:

- atomic lifecycle transitions and idempotent requests from more than one process;
- queries such as “show this run and its lineage” or “list the registered entries”;
- large tabular snapshots, projections, residuals, scenario paths, and historical panels;
- immutable raw captures whose redistribution and access must remain restricted;
- small reviewed records and public view JSON that already belong in Git releases.

Putting all of these into PostgreSQL would turn the database into an expensive blob store and
make analytical scans row-oriented. Putting all of them into files would leave concurrent
writes, indexed queries, and recovery to application code. The split must preserve the existing
contract identities and must not create a second optimizer, ledger, or source of scientific
truth inside persistence.

## Decision

Use three durable persistence classes, selected by data semantics rather than file extension:

| Class | Durable home | Purpose |
| --- | --- | --- |
| Transactional state and query metadata | PostgreSQL | Run lifecycle, entry registration, idempotency, and searchable artifact lineage |
| Immutable large or restricted bytes | Object storage; Parquet for tabular data | Captures, historical panels, projections, residuals, scenarios, and other bulk evidence |
| Reviewed release records | Git | Contracts, accepted decisions, compact measurement records, and published site views |

The current local directories remain the development adapter. This ADR does **not** add a
database, object store, dependency, migration, or network service. It fixes the boundary that
later implementation PRs must honor.

### PostgreSQL owns coordination, not analytical bytes

PostgreSQL is authoritative for mutable application state and lifecycle transitions. It stores
metadata needed to locate and verify immutable bytes, but not the bytes themselves. The first
logical schema is:

#### `runs`

One row per distinct execution attempt.

| Column | Contract and constraint |
| --- | --- |
| `run_id` | Primary key; the existing validated `RunContext.run_id` |
| `operation` | Validated runtime operation name |
| `status` | `running`, `completed`, or `failed`; terminal states never transition |
| `created_at`, `started_at`, `finished_at` | `timestamptz`; `finished_at` is required only for terminal states |
| `repository_commit` | Exactly 40 lowercase hexadecimal characters |
| `configuration_fingerprint` | SHA-256 hexadecimal digest |
| `reproducibility_fingerprint` | SHA-256 hexadecimal digest; indexed but deliberately not unique because retries are separate runs |
| `input_fingerprints` | Validated JSON object from `run_context_v1` |
| `component_versions` | Validated JSON object from `run_context_v1` |
| `deterministic_seed` | Non-negative signed 64-bit integer |
| `manifest_contract_version` | Exact manifest schema identity used by this run |
| `runtime_seconds` | Non-negative and present only for a terminal run |
| `failure_phase`, `failure_type`, `failure_message` | All absent on success; phase/type present on failure |

Lifecycle updates use a compare-and-set condition on the current status. A retry gets a new
`run_id`; it does not reset or overwrite the failed row. Creation and transition endpoints use
an idempotency key scoped to the operation, stored separately from the reproducibility
fingerprint because two intentional attempts may have identical inputs.

#### `artifacts`

One row per existing `artifact_record_v1` identity.

| Column | Contract and constraint |
| --- | --- |
| `artifact_id` | Primary key; derived exactly as it is today |
| `run_id` | Foreign key to `runs`; indexed |
| `role` | `input` or `output` |
| `kind` | Validated artifact kind; indexed with `schema_version` |
| `location` | Canonical relative POSIX object key, never a machine path or public URL |
| `checksum` | SHA-256 of the stored bytes |
| `schema_version` | Domain schema identity |
| `created_at` | `timestamptz` |

The unique slot `(run_id, role, kind, location)` preserves the file registry's refusal to
attach different bytes to the same run slot. `artifact_id` remains derived from the existing
contract fields, so moving between adapters does not change lineage identity.

#### `entry_registrations`

This is the database form of `entry_registry_v1`: `entry_id` as the primary key, `label`, and
`registered_at`. It contains only public FPL entry identifiers. User accounts, credentials,
roles, sessions, and ownership mappings are intentionally absent until an authentication/user
domain is designed.

Do not normalize domain payloads from the ledger, predictions, or scenarios into SQL tables in
this stage. A later read model may index selected fields for API queries, but it must name its
source artifact and checksum and remain rebuildable from that artifact.

### Object storage owns immutable bytes

Store each immutable object under a service-controlled key, addressed through an artifact
record. Never persist a Windows path, mounted-volume path, presigned URL, bucket credential, or
provider-specific URL in a portable contract. URLs are resolved at the adapter boundary and
may expire; `location` remains the stable relative key.

Use Parquet when the payload is a typed table that benefits from column projection or batch
scans. Partition only on bounded, commonly filtered fields such as artifact kind, schema
version, season, or gameweek. Do not partition by high-cardinality `run_id`, `snapshot_id`, or
player id. Raw source responses, manifests, reports, and small structured records stay in their
native immutable formats rather than being converted to Parquet for uniformity.

Publication order is:

1. write bytes to a temporary object key;
2. verify size and SHA-256;
3. publish the immutable final key without overwriting an existing object;
4. insert the PostgreSQL metadata/lineage row in one transaction;
5. make the run terminal only after all declared outputs are registered.

An unreferenced object can be garbage-collected after a quarantine period. A metadata row must
never point at absent or checksum-invalid bytes. Rewriting or compacting a Parquet dataset
creates a new artifact and lineage edge; it never mutates an existing artifact in place.

Raw captures and licence-restricted operational data require private buckets, encryption at
rest and in transit, least-privilege service access, audit logs, and an explicit retention rule.
They are never served from the public site bucket.

### Git keeps review and promotion authority

ADR 0003 continues to govern measurement records and evidence. Compact accepted records remain
reviewable in `docs`; bulk evidence stays outside Git. Published `web/public/data` remains a
reproducible release projection rather than a backend database export edited in place.

PostgreSQL or object storage does not decide which model/configuration is promoted. Promotion
remains an explicit reviewed change. Persistence records which promoted identity a run used.

## Adapter and transaction boundary

Core and application packages do not import SQLAlchemy, database drivers, object-store SDKs,
or provider models. Concrete adapters stay in `platform` or a higher entry-point package.

The current `RuntimeRunner` directly names `FileArtifactRegistry`. Before adding a database or
object-storage implementation, extract only the behavior the runner already consumes into a
small structural repository protocol and run the same contract tests against both adapters.
That extraction and the PostgreSQL adapter are separate implementation PRs; this ADR does not
pretend the protocol already exists.

PostgreSQL transaction boundaries surround metadata and lifecycle state only. They cannot make
an object-store write transactional, so the publication order above and a reconciliation job
handle that boundary explicitly. Application/domain work is executed outside a long-running
database transaction.

## Migration and activation

File-backed persistence stays the default until at least one measured requirement exists:

- more than one runtime process can write concurrently;
- an HTTP API needs indexed cross-run queries;
- restart recovery must find in-flight jobs;
- local storage no longer fits the measured artifact volume or retention need;
- deployment uses ephemeral filesystems.

When one of these becomes real:

1. add repository protocols without changing current behavior;
2. add PostgreSQL migrations with forward and rollback verification;
3. add an object-store adapter and failure-injection tests for publication ordering;
4. dual-read a copied dataset and compare identities, lineage, and checksums;
5. cut over one writer only after reconciliation is clean;
6. retain the file adapter for local development and contract tests.

There is no indefinite dual-write mode. During migration one writer is authoritative, and any
shadow copy is disposable until verification succeeds.

## Why not the alternatives

**PostgreSQL for everything.** Simple operationally at first, but poor for large immutable
tables and restricted raw payloads. Database backups would duplicate artifact bytes and make
retention, columnar scans, and independent integrity verification harder.

**Parquet/files for everything.** Efficient for analysis, but wrong for lifecycle transitions,
idempotency, indexed API queries, and concurrent registration.

**SQLite as the production compromise.** Useful locally, but it does not solve multi-instance
writes or ephemeral deployment storage. Adding it between the existing file adapter and
PostgreSQL creates another migration without satisfying the trigger for leaving files.

**Normalize the season ledger immediately.** It would duplicate mature immutable domain
contracts into a second representation before any API query proves the need. Keep the ledger
artifact authoritative; add rebuildable read models only for measured queries.

## Consequences

- The future hosted backend needs both a relational service and an object store once bulk
  artifacts leave local disk; the static frontend remains independently deployable.
- Backups and retention split cleanly: PostgreSQL protects coordination/query state, while
  versioned objects protect immutable bytes.
- Checksums and contract versions remain portable across local, cloud, Windows, and Linux
  adapters.
- A PostgreSQL implementation cannot be slipped into the API PR. Repository protocols,
  migrations, adapters, and deployment remain separately testable deliveries.
- The design deliberately postpones user/auth schema, cache, queues, and provider selection
  until their contracts and measured requirements exist.

## Verification obligations for later implementations

Every persistence adapter must share contract tests for:

- exact retry idempotency and conflicting-write rejection;
- immutable terminal runs and artifact records;
- deterministic lineage ordering;
- checksum verification before replay;
- UTC round trips and canonical POSIX locations;
- failure between each object-publication step without a visible broken reference;
- a copied file-backed fixture producing the same run and artifact identities after migration.
