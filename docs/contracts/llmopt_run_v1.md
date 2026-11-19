# One confirmed planning run

ADR [0018](../architecture/decisions/0018-llmopt-run-budget.md) defines admission and work
capacity. The optional `run` member of an advice POST has the exact shape in
[`llmopt_run_v1.schema.json`](llmopt_run_v1.schema.json). It carries a random 32-hex run ID
and `base` or `followup`; it never carries a provider key, forecast, or model output.
The server binds the ID to its own resolved context, league, member and window. It does
not include the reference in the advice key or immutable computation spec.

The current page saves identity before submitting, and reuses it after reload. Requests
without a run reference, including member-panel preferences, keep their legacy V1
admission outside the run budget. An identified repeated request returns its original job,
including terminal failure. It never purchases another attempt in that run. Crash recovery
does not reset a started job's work allocation.

`POST /api/v1/llmopt/runs/{run_id}/cancel` closes a run, idempotently. The response is
`{contract_version: "llmopt_run_v1", run_id: string, closed: true}`. An unregistered ID
gets a tombstone for at most five minutes; at most 1,024 such IDs are retained. Cancellation
uses the existing IP rate limiter and returns 429 when it is exhausted. An unshared queued
job is cancelled. A running solve retains its lease, publishes its valid shared cache answer
and completes, even if its initiating run closes. The closed run cannot start follow-ups.
A new run can read that answer without another job. An anonymous join to a V2 job is a
durable consumer too, so cancellation cannot revoke its queued or running work.

A pre-existing V1 job keeps its original consumer and execution policy when a run joins
it. Joining starts no additional server work; abandoning the join cannot cancel or fence
that original work. The run conservatively reserves capacity for the join, while the new
execution budget applies to newly admitted V2 jobs.

Run-owned jobs use [`backend_jobs_v2.schema.json`](backend_jobs_v2.schema.json). V2 adds
terminal `cancelled`. Run cancellation uses `queued -> cancelled`; it never uses the
schema's running cancellation edge to discard a completed shared computation.
Cancellation carries neither result nor error. V1 records and transitions are unchanged.
The public view is [`advice_job_view_v2`](advice_job_view_v2.schema.json) for these jobs: the fields of
[`advice_job_view_v1`](advice_job_view_v1.md), with the additional status `cancelled`.
The browser treats cancellation as terminal and displays no server diagnostic text.

Capacity and state refusals use HTTP 409 with stable codes:
`RUN_BASE_REQUIRED`, `RUN_BASE_CHANGED`, `RUN_CONTEXT_CHANGED`, `RUN_CANCELLED`,
`RUN_BUDGET_EXHAUSTED`, `RUN_REQUEST_INCOMPLETE`, and `RUN_STORE_UNAVAILABLE`.
The page retains completed plans and uses one simple sentence for unfinished work.

The durable ledger reserves 21 units per one-week job, 122 per three-week job, at most four
jobs. Its record distinguishes reserved capacity from actual deterministic work and native
wall reservations. Engine stop granularity is recorded honestly; an exhausted allocation
cannot start another nested solve. Running processes are never forcibly terminated.

The internal [ledger v2](llmopt_run_ledger_v2.schema.json) adds capture identity and
anonymous-consumer ownership. Old-capture runs with no open jobs are removed together
with unreferenced allocations. V1 migration preserves existing work receipts and recovers
capture identity from immutable specs where available. It never resets a live budget.
