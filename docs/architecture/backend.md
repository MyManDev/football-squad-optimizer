# Backend HTTP Boundary

The versioned HTTP surface above the application/runtime contracts. This document defines the
target; `feature/backend-api-contract` does not install FastAPI or start a server.

Companion contracts:

- [`backend_api_v1`](../contracts/backend_api_v1.schema.json) defines normalized commands and
  service, run, and error responses.
- [`ui_view_v1`](../contracts/ui_view_v1.schema.json) remains the response contract for every
  read endpoint used by the React application.
- [platform and runtime boundary](platform_runtime.md) defines execution and provenance.
- [ADR 0005](decisions/0005-persistence-boundaries.md) defines the future storage split.

## Dependency direction

```text
React / API client
        |
        v
HTTP adapter (FastAPI later)
        |
        v
platform runtime and query adapters
        |
        v
application public use cases and ui_view_v1
        |
        v
research engine
```

HTTP handlers may compose public `squadopt.platform` services. Platform code may consume public
`squadopt.application` commands and views. Neither layer may import private functions from
`scripts/` or reproduce prediction, optimization, planning, live-ledger, or evaluation logic.

FastAPI, Pydantic transport models, Uvicorn, authentication, database drivers, queues, caches,
and cloud SDKs remain outside `application` and the research engine. FastAPI will be an
optional installation extra so research-only users do not install a web stack.

## Version and media type

Versioned routes live below `/api/v1`. JSON responses use `application/json`; UTF-8 is assumed.
The API version and a document's contract version are different:

- route version `v1` controls HTTP compatibility;
- `backend_api_v1` controls command/run/error document fields;
- `ui_view_v1` controls read payloads rendered by the web application.

Breaking a document shape requires a new contract. Breaking route semantics requires a new
route version. Adding an optional endpoint without changing existing documents does neither.

## Read side

The first FastAPI implementation is read-only. It serves the same `ViewEnvelope` documents
that `python -m scripts.build_site` writes today; it does not wrap them in a second API envelope.

| Method and route | `ui_view_v1` payload | Meaning |
| --- | --- | --- |
| `GET /health` | `ApiServiceInfo`, not a view | Process is able to answer HTTP; no solver or external dependency call |
| `GET /api/v1/info` | `ApiServiceInfo`, not a view | Service and API contract identity |
| `GET /api/v1/seasons` | `SiteIndex` | Available seasons, gameweeks, and latest published decision |
| `GET /api/v1/seasons/{season}/status` | `StatusView` | Current operational status and recent run events |
| `GET /api/v1/seasons/{season}/league` | `LeagueView` | League comparison for the captured season |
| `GET /api/v1/seasons/{season}/ledger` | `LedgerView` | Recorded decisions and settled outcomes |
| `GET /api/v1/seasons/{season}/gameweeks/{gameweek}/recommendation` | `RecommendationView` | One frozen recommendation |
| `GET /api/v1/seasons/{season}/gameweeks/{gameweek}/pool` | `PoolView` | The projected player pool behind that recommendation |

The query adapter reads validated application views or their checked artifacts. It never sends
raw ledger files, snapshot payloads, arbitrary filesystem content, pandas records, NaN, or
provider credentials. A missing season/gameweek/view is `404`, not an empty success document.

The initial frontend may continue using committed `/data` JSON while these endpoints stabilize.
Pages migrate one at a time; static JSON and HTTP must validate against the same `ui_view_v1`
schema during that transition.

## Command side

Command routes arrive only after the read side works through the application boundary:

| Method and route | Operation |
| --- | --- |
| `POST /api/v1/seasons/{season}/gameweeks/{gameweek}/decide` | `gameweek.decide` |
| `POST /api/v1/seasons/{season}/gameweeks/{gameweek}/settle` | `gameweek.settle` |
| `POST /api/v1/seasons/{season}/tick` | `season.tick` |
| `GET /api/v1/runs/{run_id}` | retrieve the terminal `ApiRunResponse` |

Every write requires an `Idempotency-Key` header. The HTTP adapter combines that header, route
parameters, and the JSON body into an `ApiCommandRequest`. This normalized object is what gets
fingerprinted and registered; clients do not post it wholesale as a request body.

The JSON bodies contain only client choices:

- decide: optional `snapshot_id`, `projection_artifact_id`, and `chip`, plus explicit
  `mode` (`live` or `replay`);
- settle: optional `snapshot_id`;
- tick: `dry_run` only.

The server injects workspace roots, ledger roots, repository commit, promoted component
versions, clock, capture adapter, and credentials. No request accepts `snapshot_root`,
`ledger_root`, `archive_root`, a local projection path, a bucket URL, or any other server path.
An in-season projection is selected by registered artifact identity and checksum, never by an
arbitrary path supplied over HTTP.

The API calls the same `DecideRequest`, `SettleRequest`, `TickRequest`, and `RuntimeRunner` path
as the CLI after resolving those server-owned dependencies. HTTP handlers do not import or call
the solver directly.

## Request identity and concurrency

`ApiCommandRequest.request_fingerprint` covers the contract version, operation, route identity,
and every client choice. It excludes `Idempotency-Key`:

- same key + same fingerprint returns the original run/result;
- same key + different fingerprint returns `409 STATE_CONFLICT`;
- different key + same fingerprint is a distinct attempt and may receive another `run_id`;
- replay mode requires an explicit immutable `snapshot_id`.

The first synchronous implementation may execute in the HTTP process. Before more than one
writer exists, write operations need a `(season, gameweek)` lock. A second conflicting command
returns `409`; it does not race the ledger. PostgreSQL advisory locks or a queue are later
adapter choices, not part of `backend_api_v1`.

## Run response

A started command returns `ApiRunResponse`. It carries both identities that operators need:

- `run_id` identifies this attempt;
- `request_fingerprint` identifies the normalized client request;
- `reproducibility_fingerprint` identifies code, configuration, inputs, component versions,
  and deterministic seed;
- `output_artifact_ids` binds the response to registered lineage.

The response is terminal in v1: `completed` or `failed`. A future queue needs a separately
versioned job resource for `queued` and `running`; those states are not added speculatively.
A completed response may contain a small JSON-native result. Readable recommendations remain
`ui_view_v1`, and large results remain artifacts rather than being embedded in HTTP.

## Error contract

Errors are safe public values, never raw exception representations. `ApiError` contains a stable
uppercase `code`, a human-readable `message`, optional `run_id`, and JSON-native `details`.
It must not contain a traceback, local path, SQL text, secret, raw provider response, or solver
debug dump.

| HTTP | Stable code | Use |
| ---: | --- | --- |
| 400 | `BAD_REQUEST` | Malformed JSON, header, or route value |
| 401 | `UNAUTHORIZED` | Reserved until authentication exists |
| 404 | `NOT_FOUND` | Requested season, gameweek, run, or artifact is absent |
| 409 | `STATE_CONFLICT` | Idempotency mismatch, duplicate mutation, or active lock |
| 422 | `VALIDATION_FAILED` | Structurally valid request rejected by an application contract |
| 500 | `INTERNAL_ERROR` | Unexpected failure; public message is sanitized |

An error before a run starts uses `ApiErrorResponse`. A failure after a run starts uses a failed
`ApiRunResponse`, and the nested error must carry the same `run_id`. A solver reporting no
feasible solution is not automatically an infrastructure `500`; the application adapter maps
it according to the domain result it actually received.

## Deliberately absent from v1

- no user or authentication domain;
- no PostgreSQL, ORM, or migration runtime;
- no Redis, queue, worker, cache, or background job status;
- no arbitrary optimization/research endpoint;
- no upload endpoint for raw snapshots or model artifacts;
- no browser call directly to the upstream FPL API;
- no CORS wildcard or public command endpoint by default.

These features require their own contracts, tests, and operational decisions. They are not
implicit consequences of adding FastAPI.

## Implementation acceptance

The following FastAPI PR must demonstrate:

1. API dependencies are optional and do not enter the core dependency set.
2. `/health` and `/api/v1/info` return schema-valid `ApiServiceInfo` without touching the solver.
3. At least one read route returns the exact schema-valid `ui_view_v1` document produced by the
   application read side.
4. Import boundaries prevent HTTP code from reaching optimization, prediction, planning,
   scenarios, or private scripts directly.
5. Test clients exercise success, missing-resource, invalid-route, and sanitized-error paths.
