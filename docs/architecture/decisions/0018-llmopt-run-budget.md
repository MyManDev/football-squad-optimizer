# ADR 0018: One durable budget per LLMOPT run

- Status: proposed
- Date: 2026-11-18
- Decider: project owner
- Related: ADR 0017; Phase 1 PR #1464; `llmopt_run_v1` and `backend_jobs_v2`

## Problem

Four mounted result slots do not limit a run across retries, reloads, changed drafts or
API processes. A solver invocation is not a server job. The frozen Phase 1 workload admits
four jobs and makes twelve internal calls at one week, sixteen at three weeks.

## Decision

1. A confirmed draft has a random 128-bit run ID, saved before a request starts. Reloads
   reuse it. A new confirmation after an edit has a new identity; editing first abandons
   the old run. Run metadata contains no provider credential and is never model input.
2. The server binds the ID to the resolved capture/context, member, league and window,
   then persists every distinct answer request and its job association. A run admits at
   most **four jobs**. Repeats join/read the original job, including terminal failures;
   they never buy another attempt within the same run. Cache hits create no job.
3. The base must complete before follow-up admission. This is checked on the server as
   well as in page orchestration. Failed/abandoned bases cannot start follow-ups.
4. Work is reserved durably before the queue write. A crash may lose spare capacity,
   never erase an admission. API/worker restarts retain the same ledger. Corruption fails
   closed. Queue transactions and ledger transactions always acquire ledger first.
5. The run's work-capacity limits are **84 units at one week** and **488 at three weeks**.
   One unit is one CP-SAT deterministic unit, or a reservation of at most 30 native-solver
   wall seconds. Native reservations are charged before execution and are not refunded.
   This is a declared capacity measure, not a claim that the two engines consume equal CPU.
   The 30-second conversion is the existing 1,800-second / 60-unit production ratio.
   Phase 1 receipts show a one-unit hold probe, a 20/60-unit main budget and, at three
   weeks, a one-unit native-witness certificate. The worst fallback path therefore reserves
   `20 + 1 = 21` units at one week and `60 + 1 + 1 + 1800/30 = 122` at three weeks.
   Four such reservations give 84 and 488. No native invocation is treated as free.
6. Every nested CP call is limited to remaining admitted work, and actual deterministic
   work is metered. Native execution first reserves its maximum wall allowance in these
   units; if that reservation cannot fit, the existing bounded CP fallback is used.
   Engine stop granularity can exceed a requested deterministic limit: the observed value
   remains visible and no further call starts after exhaustion. No accounting tolerance is
   enlarged or observed work clamped. Reservation totals, observed work and elapsed time
   remain distinct. Unused job reservations are not silently recycled into more jobs.
7. Cancellation closes the run before touching the queue. Unshared queued jobs become
   terminal `cancelled` jobs and are removed from the open queue. A running solver is not
   killed: its result is ignored for the abandoned run and cannot start another request.
   Shared jobs are retained for other active consumers. `backend_jobs_v1` remains readable;
   run-owned jobs use `backend_jobs_v2` with the explicit queued-to-cancelled transition.
   Joining a pre-existing V1 job is read-only: it creates no work, and does not transfer its
   original consumer's ownership or execution policy. A joined run still reserves capacity
   conservatively, but only newly admitted V2 work receives the run's execution fence.
8. A capacity refusal shows completed plans and one bilingual sentence for unfinished
   work. Internal solver/budget/proof details do not become page explanation text.
9. Advice-cache identity and immutable job-spec identity exclude run metadata: the same
   computed answer can still be shared. Job ownership/capacity is indexed separately by
   job ID, not stored as a conflicting meaning under the shared answer key.

## Compatibility and morning decisions

The new page always supplies `llmopt_run_v1` metadata. Cached legacy requests remain
readable; new preference computation without run identity is refused rather than creating
unaccounted work. This requires coordinated frontend/backend release, which this work does
not perform. Confirm that conservative migration policy before deployment.

Session storage has a history-state fallback containing only the already-safe plan session.
If neither can retain run identity, new server work is refused rather than making reloads
create another run. Confirm that usability choice before release.

Five-week advice is outside the one/three-week planning page and retains its legacy
transport. Run metadata explicitly rejects that window. The new durable adapter is
registered beside the existing flat backend modules until their unit move; the existing
dependency rules and architecture tests remain in force.

The work ceiling is an admission-capacity ceiling with disclosed engine stop granularity,
not a hard operating-system CPU-time kill. Keeping a non-interruptible solve fenced is safer
than terminating the single worker while it may publish an answer.

## Acceptance evidence

Run-ledger/service tests cover concurrent admissions, five-plus requests, retries after
terminal failure, reconstruction after restart, cached bases, base-first admission and
cancellation races. Browser tests cover reload and edited drafts. Measurement uses the
unchanged Phase 1 inputs; its records and commands are listed in the phase PR.
