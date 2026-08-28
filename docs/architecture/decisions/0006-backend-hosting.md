# ADR 0006 — Host the advice backend beside Pages, not inside it

- **Status:** accepted (amended per the platform owner's review, 2026-08-27)
- **Date:** 2026-08-27
- **Decider:** Ertuğrul, with the platform owner reviewing
- **Related:** [ADR 0004](0004-cloudflare-pages-deployment.md),
  [ADR 0005](0005-persistence-boundaries.md),
  [backend contracts](../backend.md)

## Context

ADR 0004's revisit trigger has fired: the product now gains server-side compute. A league
member presses Hesapla and a CP-SAT solve runs on their behalf — the on-demand advice
program's whole point — and 0004 already records both halves of the consequence: Pages is
reconsidered "if the product gains … server-side compute", and "the FastAPI service under
`src/squadopt/api` cannot run on Cloudflare Pages and requires a separate backend-hosting
decision before it is exposed publicly". This is that decision.

The workload is characterized by measurement, not guess. One member's plan solves in
3.0–29.6 s wall on a single thread under the deterministic budget (the GW2 capture,
fifteen members); CP-SAT runs one search worker by design, so a worker process scales by
replication, never by threads. The deployment units and their write sets are already
decided in the program's plan: Pages (static origin), `squadopt-api` (stateless,
imports no solver), `squadopt-worker` (CPU-bound, the only thing that scales),
`squadopt-ops` (the existing CLI, sole writer of ledger and site data).

## Decision

- **Pages stays exactly what it is**: the static origin, no `_worker.js`, no
  `functions/`, preflight-enforced. The site keeps working with the backend down or
  absent — `VITE_ADVICE_API_ORIGIN` defaults to empty, and empty means today's static
  site, byte for byte.
- **The API and the worker are one container image, two processes, on a separate
  origin** — a Linux x86-64 host. Not for wheel availability: the pinned
  `ortools>=9.15.6755` publishes Linux aarch64 wheels too, so either architecture
  would install. x86-64 is required because the solver's determinism and its time
  budget were **measured** on x86-64, and a deployment on an unmeasured architecture
  would be claiming numbers nobody has; aarch64 becomes eligible the day its parity
  is measured, not before. A single vCPU per worker replica is sufficient: the solve
  is single-threaded and the budget deterministic.
- **The backend host must provide one shared ReadWrite filesystem, mounted by every
  process that touches the store.** "Persistent disk" understates the requirement:
  the API writes the job queue that the worker reads, and every replica must observe
  the same immutable cache — a volume that is persistent but private to one service
  (Render and Railway service volumes, for example) cannot serve the stated split.
  The mount must carry the primitives the adapters were built and reviewed on:
  `O_EXCL` exclusive create (claim markers), hard-link create-once (`os.link` from a
  finished temporary file — cache entries, job submission, the open-job index), and
  mtime as a heartbeat. The accepted day-one store is a **durable Azure Files NFS
  mount**, not Container Apps local storage and not an SMB mount. Both containers
  mount the same path ReadWrite. A startup capability probe must prove exclusive
  create, hard-link no-overwrite, cross-container visibility, heartbeat mtime and
  persistence across a replacement before API ingress is enabled. A failed probe
  keeps the service unready; it is never downgraded to a local-disk fallback.
- **Losing the store's durability or its semantics fires ADR 0005's trigger
  knowingly, never silently.** An ephemeral disk, or a shared mount that fails the
  primitive checks, is "atomic lifecycle transitions from more than one process"
  territory: record the trigger as fired, adopt the Postgres/Redis adapters
  deliberately, and say so in this file's status history rather than working around
  it.
- **CORS is an allowlist, never a wildcard**; the allowed origins are the Pages
  domains, read from configuration, not code. Secrets live in the host's environment;
  nothing secret reaches the browser.

## Initial topology, and what promotes it

- **Start as one Container App replica with two containers from the same image**:
  one API command (uvicorn serving `squadopt-api`) and one worker command. Only the
  API container receives external ingress; the worker has no public listener. Both
  mount the same durable Azure Files NFS share ReadWrite from day one. Container Apps
  local storage is explicitly ineligible because it is ephemeral across restart and
  replica replacement; one replica limits concurrency but does not make local state
  durable.
- **Provider**: Azure Container Apps, per the platform owner's provider review. The
  deployment image is `linux/amd64`, the platform profile selected for this topology;
  this also matches the architecture on which the solver budget was measured. This
  is not a wheel-availability claim: the pinned OR-Tools release also publishes Linux
  aarch64 wheels. Secrets stay in environment configuration. AWS ECS/Fargate + EFS
  fits the same durable shared-filesystem shape with more operational surface, and
  remains the recorded alternative.
- **Promotion trigger**: the same measurement "When to revisit" names — queue depth
  or job wait at the deadline peak exceeding what one worker serves. Promotion means
  splitting the worker into its own Container App and then increasing worker replicas,
  while retaining the same already-probed Azure Files NFS share. The storage boundary
  does not change during promotion. If the share later fails durability or primitive
  checks, that is the ADR 0005 trigger and requires the managed-store migration.

## Consequences

- A second deploy surface exists and can lag or fail independently of Pages; the site
  must degrade to static behavior, not to an error — this is a stated product
  requirement, tested in the web client, not an aspiration.
- Worker scaling is horizontal and bounded by the queue: replicas × concurrency 1.
  Before adding a replica, read the cache hit rate; a high hit rate makes a new worker
  waste (the plan's scaling order: standings validation → cache → worker replicas →
  only then managed stores).
- The ops process does not move: captures, decides, settles, site builds stay where
  they are, on the machine that owns the ledger. The backend reads what ops publishes;
  it never writes it.

## Rollback

Unset `VITE_ADVICE_API_ORIGIN` (or let the backend die): the site is the static site
again, exactly as before this decision. The backend container can be deleted whole; it
owns no data the ledger needs — the cache recomputes, and pending jobs are recomputable
requests by construction.

## When to revisit

If measured queue depth or job wait says one host cannot serve the league's deadline
peak; if the shared-filesystem requirement fails on the chosen host — no mount, or a
mount that fails the primitive checks (see above — that is ADR 0005's trigger, handled
there); or if a second league multiplies entry counts past what an operator-seeded
registry sensibly carries.
