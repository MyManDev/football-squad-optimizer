# One confirmed planning run

ADR [0018](../architecture/decisions/0018-llmopt-run-budget.md) defines admission and work
capacity. The optional `run` member of an advice POST has the exact shape in
[`llmopt_run_v1.schema.json`](llmopt_run_v1.schema.json). It carries a random 32-hex run ID
and `base` or `followup`; it never carries a provider key, forecast, or model output.
The server binds the ID to its own resolved context, league, member and window. It does
not include the reference in the advice key or immutable computation spec.

The current page saves identity before submitting, and reuses it after reload. New
one/three-week preference work on the composed backend requires this reference. Legacy cache reads and
ordinary advice requests remain compatible. A repeated request returns its original job,
including terminal failure. It never purchases another attempt in that run. Crash recovery
does not reset a started job's work allocation.

`POST /api/v1/llmopt/runs/{run_id}/cancel` closes a run, idempotently. The response is
`{contract_version: "llmopt_run_v1", run_id: string, closed: true}`. An unregistered ID
gets a tombstone so cancellation can win a race with first submission. An unshared queued
job is cancelled; a running solve retains its lease and its result is discarded for the
closed run. A shared job remains available to its active consumers.

Run-owned jobs use [`backend_jobs_v2.schema.json`](backend_jobs_v2.schema.json). V2 adds
terminal `cancelled` and the edges `queued -> cancelled`, `running -> cancelled`; the
running edge is used only when computation returns, never to interrupt the solver.
Cancellation carries neither result nor error. V1 records and transitions are unchanged.
The public view is `advice_job_view_v2` for these jobs: the fields of
[`advice_job_view_v1`](advice_job_view_v1.md), with the additional status `cancelled`.
The browser treats cancellation as terminal and displays no server diagnostic text.

Capacity and state refusals use HTTP 409 with stable codes: `RUN_ID_REQUIRED`,
`RUN_BASE_REQUIRED`, `RUN_BASE_CHANGED`, `RUN_CONTEXT_CHANGED`, `RUN_CANCELLED`,
`RUN_BUDGET_EXHAUSTED`, `RUN_REQUEST_INCOMPLETE`, and `RUN_STORE_UNAVAILABLE`.
The page retains completed plans and uses one simple sentence for unfinished work.

The durable ledger reserves 21 units per one-week job, 122 per three-week job, at most four
jobs. Its record distinguishes reserved capacity from actual deterministic work and native
wall reservations. Engine stop granularity is recorded honestly; an exhausted allocation
cannot start another nested solve. Running processes are never forcibly terminated.
