# Backend HTTP Boundary

The versioned HTTP surface above the application/runtime contracts. The transport-neutral
contract landed first; `squadopt.api` implements published-view reads and optional on-demand
advice routes. The default ASGI app serves the published views; advice needs injected stores,
submission services and a worker composition before it can compute anything.

Companion contracts:

- [`backend_api_v1`](../contracts/backend_api_v1.schema.json) defines normalized commands and
  service, run, and error responses.
- [`ui_view_v1`](../contracts/ui_view_v1.schema.json) remains the published season/gameweek
  view contract. League-member advice uses `provisional_league_ui_v1` documents and the
  separate advice-job resource.
- [`backend_jobs_v1`](../contracts/backend_jobs_v1.schema.json) defines the queued advice
  lifecycle; it is separate from the terminal operator-run response described below.
- [platform and runtime boundary](platform_runtime.md) defines execution and provenance.
- [ADR 0005](decisions/0005-persistence-boundaries.md) defines the future storage split.

## Dependency direction

```text
React / API client
        |
        v
HTTP adapter (`squadopt.api` / FastAPI)
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

FastAPI, Uvicorn, authentication, database drivers, queues, caches, and cloud SDKs remain
outside `application` and the research engine. FastAPI, Uvicorn, and the runtime JSON Schema
validator are in the optional `api` installation extra, so research-only users do not install
a web stack. Transport models continue to use the framework-neutral platform contracts rather
than a duplicate set of Pydantic response classes.

## Running the default published-view adapter

Install the optional dependencies and start the ASGI app from the repository root:

```console
python -m pip install -e ".[api]"
python -m uvicorn squadopt.api:app --host 127.0.0.1 --port 8000
```

`create_app(data_root=...)` is the deployment configuration seam. Its default is
`web/public/data`; the path is server-owned and can never be supplied by an HTTP request. The
file-backed adapter maps fixed routes to fixed relative filenames, resolves each target below
the configured root, rejects non-finite JSON, and validates the exact route-specific
`ui_view_v1` payload before returning it. Read responses use `Cache-Control: no-cache`.

The Cloudflare Pages deployment remains a static React deployment and does not run this Python
process. [ADR 0006](decisions/0006-backend-hosting.md) records the separate API/worker hosting
decision and durable shared-store requirements. That decision is not evidence that a deployment
is running. `create_app(allowed_origins=...)` implements explicit CORS allowlisting; an empty
tuple enables no cross-origin access and a wildcard is rejected.

## Composing the advice backend

`squadopt.api:app` is the module-level default: it serves published views and answers 503 on
every advice route, because `create_app()` defaults `advice_store` and `advice_submit` to
`None`. That default is deliberate and stays — an api built without a store must not present
an empty cache as a computed absence.

The deployment's app is the other half. `squadopt.platform.backend_runtime` is the composition
root: it reads the server's own environment, opens **one** store, and builds the queue, the
cache, the read store, the submission service and the capture context that the api and the
worker share. `squadopt.api.runtime` hands those to `create_app`. The split follows the layer
contract rather than taste — `api` sits above `platform`, so platform may not import the
FastAPI wiring, and whatever calls `create_app` has to live in `api`.

```console
uvicorn --factory squadopt.api.runtime:build_app --host 0.0.0.0 --port 8000
```

Configuration is entirely server-side; a request names a league, a member, a strategy and a
window, never a path.

| Variable | Required | Meaning |
| --- | --- | --- |
| `SQUADOPT_BACKEND_STORE_ROOT` | yes | the one shared ReadWrite mount; `jobs/` and `cache/` are derived from it |
| `SQUADOPT_BACKEND_SITE_DATA_ROOT` | yes | what ops publishes; the league tree the read side answers `connected` from |
| `SQUADOPT_BACKEND_SNAPSHOT_ROOT` | yes | captures; the most recent one is the current context |
| `SQUADOPT_BACKEND_HANDOFF_ROOT` | yes | projection handoffs, addressed by the capture's own season and gameweek |
| `SQUADOPT_BACKEND_ALLOWED_ORIGINS` | no | comma-separated CORS allowlist; a wildcard is refused |
| `SQUADOPT_BACKEND_SEASON` | no | override; otherwise inferred from the capture |
| `SQUADOPT_REPOSITORY_COMMIT` | in a container | part of every answer's identity; falls back to `git rev-parse` locally |

The backend answers only from a capture that has a **projection handoff** — the same handoff
the decision path reads. The opening gameweek's archive-panel route is deliberately not offered
here: a projection whose identity nobody can name has no business entering a cache key. No
capture, no handoff, or an unreadable one means no context, and no context means `/ready`
reports `capture_context: false` rather than the service answering from whatever it can find.

## What a queued job is for, and who computes it

`AdviceJob` carries three identities and every one is a one-way SHA-256 digest — `job_id`
names the record, `request_fingerprint` names the normalized request, `cache_key` names the
answer's address. Keeping them apart is what stops a cache serving one member another
member's plan, but it leaves a claimed job unable to say which member or strategy it was
asked about. A digest does not invert.

So the request travels *beside* the job. `AdviceSubmitService` writes one
`advice_job_spec_v1` record at the answer's own address before the job is enqueued — before,
never after, because a worker may claim the instant the record lands. The worker reads it
back by `job.cache_key`. Nothing about `backend_jobs_v1`, its schema, or the public job view
changes.

The spec also records the context the request was **accepted under**, which is what lets the
worker tell two situations apart:

- the capture it names is still the one this process answers from — compute;
- the deployment has moved to a newer capture — refuse with `CONTEXT_UNAVAILABLE`. Computing
  from today's inputs and filing the answer under yesterday's key would be silent corruption,
  and the member is better told to ask again.

A rival that the strategy ignores is dropped from the spec exactly as `advice_cache_key`
drops it before hashing. Requests that reach one address describe one question, or a
write-once store is right to refuse them.

`compute` returns the served document, and `generated_at_utc` is the **capture's** instant,
not the clock's. These bytes live at a content-addressed key whose immutability is checked on
every write, so a wall-clock field would make an honest recomputation — after a recovered
claim, say — indistinguishable from a determinism defect.

### The loop

```console
python -m squadopt.platform.advice_worker
```

Deployment configuration, the startup store probe, a local two-process run and the rollback
step are in the [advice backend runbook](../backend_runbook.md).

One computation at a time per worker: CP-SAT runs a single search worker by design and a
replica scales by replication (ADR 0006). An empty queue waits rather than spins. SIGTERM and
SIGINT are honoured *after* the job in hand finishes, so a container stop costs nobody their
solve. Abandoned claims are walked back periodically through the contract's own
`running -> queued` edge, which increments `attempt`; past `--max-attempts` (default 3) the
job is failed with `TOO_MANY_ATTEMPTS` rather than crash-looping. The claim's lease is 300
seconds against a measured 3.0–29.6 s *single* solve, and one member's plan is several
solves, so the claim is kept alive while the computation runs: `run_advice_worker_once`
refreshes it through `queue.heartbeat` on a background thread every `heartbeat_seconds`,
and the loop's default is a third of the lease.

Refusals the compute side reaches deliberately carry their own code (`CONTEXT_UNAVAILABLE`,
`REQUEST_UNREADABLE`, `TOO_MANY_ATTEMPTS`); an unexpected exception is still `ADVICE_FAILED`
with a sanitized message. Neither shape puts a traceback, a local path or a secret on a
public endpoint.

## Version and media type

Versioned routes live below `/api/v1`. JSON responses use `application/json`; UTF-8 is assumed.
The API version and a document's contract version are different:

- route version `v1` controls HTTP compatibility;
- `backend_api_v1` controls command/run/error document fields;
- `ui_view_v1` controls read payloads rendered by the web application.

Breaking a document shape requires a new contract. Breaking route semantics requires a new
route version. Adding an optional endpoint without changing existing documents does neither.

## Read side

The published-view read side serves the same `ViewEnvelope` documents
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

## Implemented advice commands and jobs

| Method and route | Meaning |
| --- | --- |
| `GET /api/v1/leagues/{league_id}` | Published league connection state |
| `GET /api/v1/leagues/{league_id}/entries/{entry_id}/advice` | Cache lookup for strategy, window and optional rival; never starts a solve |
| `POST /api/v1/leagues/{league_id}/entries/{entry_id}/advice` | Cached answer (`200`) or accepted job (`202`) |
| `GET /api/v1/advice-jobs/{job_id}` | Public job state: queued, running, completed or failed |
| `GET /ready` | Injected readiness checks, or static data-root readiness in the default app |
| `GET /metrics` | Advice metrics when configured; otherwise `404` |

Advice routes return `503 ADVICE_BACKEND_DISABLED` when their required injected service is
absent. A missing current capture context is a readiness failure; a valid context with no
cached answer is a cache miss. These are different states.

The POST body contains `strategy`, `window` and optional `rival_entry_id`. An explicit
`Idempotency-Key` is supported; the advice submission service also handles its absence.
Reusing an explicit key with a different request conflicts. Equivalent open work is deduplicated,
and configured request buckets can reject excess submissions. The in-memory limiter is per API
process; replicas do not share it automatically.

`run_advice_worker_once` claims a job, calls an injected compute function, writes the immutable
cache entry and records completion or failure. The production compute function lives in
`squadopt.platform.advice_worker`: it reads the job's spec back, checks the capture it names
against the current capture context, and calls the public application advice service with the
captured picks, projection and rules. The worker loop (`advice_worker.py`), the capture-context
provider (`backend_runtime.CaptureContextProvider` over `capture_context.py`) and the one-store
composition (`backend_runtime.py`) are in the repository; what is not is a running deployment
of them, and the default `app = create_app()` deliberately does not assemble those services.

The API accepts window values 1, 3 and 5 at the transport boundary. That is not a claim that the
current engine computes all three: `advise_entry` currently computes window 1 and refuses the
others. Strategy registration also differs from executable support; only wired constraints
can produce a plan. The current public advice envelope contains expected-point trade-offs,
not member-facing probability claims.

The frontend's general pages still use `StaticDataClient`. The member advice client optionally
uses `VITE_ADVICE_API_ORIGIN` and can fall back to the published static answer. The member page
renders returned advice and retains compute controls when published advice is absent. Which
selections may request a computation is decided in one place, `canComputeAdvice` in
`web/src/features/league/advice/adviceSelection.ts`, and it mirrors `advise_entry`'s own
refusals: window 1 only, and either `saf-puan` (rival-free) or a member strategy
(`ortak-koru`, `fark-yarat`) with a rival named. Longer windows and the legacy play modes are
displayed from the published tree only; the play modes are not aliases for the member
strategies.

Advice responses must match the selected league, member, mode, window and displayed season/week.
A refreshed squad invalidates earlier jobs and results. Static answers are labelled published
plans, and request rejections are not turned into successful static computations. Enabling an
origin still requires a deployment of the worker and capture-context assembly described above.

## Planned operator HTTP commands

The routes below describe the operator-command design; they are not implemented HTTP routes
in the current `create_app`. The corresponding application/runtime operations remain callable
through their existing entry points. The remainder of this section describes the planned
operator request and terminal-run contracts, not the implemented advice-job resource above.

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
- no PostgreSQL, ORM, or migration runtime, and no Redis: the queue, the cache and the worker
  are the file-backed ones on the shared store of ADR 0006, and the only job status is the
  `backend_jobs_v1` advice-job resource above;
- no arbitrary optimization/research endpoint;
- no upload endpoint for raw snapshots or model artifacts;
- no browser call directly to the upstream FPL API;
- no CORS wildcard or public command endpoint by default.

These features require their own contracts, tests, and operational decisions. They are not
implicit consequences of adding FastAPI.

## Read-only implementation guarantees

The FastAPI implementation demonstrates:

1. API dependencies are optional and do not enter the core dependency set.
2. `/health` and `/api/v1/info` return schema-valid `ApiServiceInfo` without touching the solver.
3. At least one read route returns the exact schema-valid `ui_view_v1` document produced by the
   application read side.
4. Import boundaries prevent HTTP code from reaching optimization, prediction, planning,
   scenarios, or private scripts directly.
5. Test clients exercise success, missing-resource, invalid-route, and sanitized-error paths.
