# `advice_job_view_v1`: an advice job as the page reads it

`GET /api/v1/advice-jobs/{job_id}` answers with this document while a member waits for a dynamic calculation (`AdviceSubmitService.public_job_view` in `src/squadopt/platform/advice_submit.py`). It names the fields it serves instead of serving the stored job record (`backend_jobs_v1`), which keeps the client's idempotency key and the worker's failure text off the public endpoint.

The examples are in [`advice_job_view_v1.examples.json`](advice_job_view_v1.examples.json), one per status.

## Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `contract_version` | `"advice_job_view_v1"` | This contract. |
| `job_id` | string | The job, as the submit answered it. |
| `status` | `queued`, `running`, `completed` or `failed` | Where the job is. |
| `created_at_utc`, `updated_at_utc` | UTC instant | When the job arrived and when its record last changed. |
| `attempt` | integer | The attempt on the job, from 1. When a worker dies, recovery puts the job back in the queue with the attempt one higher. |
| `error_code` | string or `null` | Why a `failed` job failed; `null` otherwise. |
| `queue_position` | integer or `null` | While `queued`: how many queued jobs will be claimed before this one, 0 when it is next. `null` in every other status. |
| `progress` | `{done, total}` or `null` | While `running`: the documents this attempt has solved (`done`) out of those it has to solve (`total`). `null` in every other status, at the start of `running`, before the attempt has recorded its first count, and on a poll that could not read the count. |
| `workers` | `{busy, total}` or `null` | The workers alive now (`total`) and how many of them hold a job (`busy`). `null` when the service cannot read them. |

The last three fields came with #978's progress item (shape fixed in #978 comments 6570843186 and 6578603402). A client treats each of them as possibly absent, because a service older than them does not send them. A client that reads only `job_id`, `status` and `error_code` reads the same as before.

## Rules

- **The claim order** is the oldest `created_at_utc` first, then the job id (`queue_contracts.claim_order`). `queue_position` counts in that order, so a waiting job's position only goes down, except by one when a worker dies and its job goes back to the queue ahead of it.
- **`progress` counts documents, never time.** The asked document counts, and so does each document it is priced or compared against that the cache does not already hold (`advice_menu.documents_to_solve`); a rival window under a Top 100 setting counts at most 3. `total` is at least 1 and fixed for an attempt, `done` only goes up and never passes `total`, and a new attempt starts again at 0. The page shows it as a count ("1/3") and a bar, never as a percentage (#954), and a job of one document as the bar alone. It keeps the last count through a poll that could not read it, while the attempt is the same.
- **`queue_position` and `workers` come from one look** that `/ready` and every poll share for five seconds (`READINESS_RECHECK_SECONDS`), so they can be up to five seconds older than `status`.
- **A worker is alive** when its heartbeat was rewritten in the last 120 seconds, and **busy** while its heartbeat names the job it holds.
