# ADR 0006 — Host the advice backend beside Pages, not inside it

- **Status:** proposed (open to the platform owner's approval)
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
  origin** — a Linux x86-64 host, because `ortools` wheels are x86-64 Linux and the
  solver's determinism was measured there. A single vCPU per worker replica is
  sufficient: the solve is single-threaded and the budget deterministic.
- **The backend host must provide a persistent disk.** The first adapters are
  file-backed by design (advice cache, job queue — ADR 0005's "start with files"
  posture). An ephemeral disk would silently fire ADR 0005's PostgreSQL trigger — jobs
  and cache lost on every restart is "atomic lifecycle transitions from more than one
  process" territory — and a trigger fired by accident is the worst way to adopt a
  database. If a chosen host cannot offer persistent disk, that is the trigger firing
  **knowingly**: record it as fired, adopt the Postgres/Redis adapters deliberately,
  and say so in this file's status history rather than working around it.
- **CORS is an allowlist, never a wildcard**; the allowed origins are the Pages
  domains, read from configuration, not code. Secrets live in the host's environment;
  nothing secret reaches the browser.

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
peak; if the persistent-disk requirement fails on the chosen host (see above — that is
ADR 0005's trigger, handled there); or if a second league multiplies entry counts past
what an operator-seeded registry sensibly carries.
