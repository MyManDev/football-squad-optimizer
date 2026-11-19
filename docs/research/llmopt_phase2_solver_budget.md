# Real solver controls under durable work allocations

The [record](llmopt_phase2_solver_budget.json) was produced by commit
`a72858f10d2d95935c69ec6d170f08fb7acefffc` with
`python -m docs.research.llmopt_phase2.measure_solver_budget`.
It complements the separate [admission replay](llmopt_phase2_admission.md).

All twenty frozen Phase 1 member-weeks were solved sequentially at both windows,
using their original control settings and unchanged input hashes. Each execution
obtained a real durable V2 allocation before computing. Native work reserved its
allowance before starting. No tests or live requests ran alongside the measurement.

| Window | Controls | Equal numeric objectives | Equal infeasibilities | Equal statuses and decisions | Maximum charged units | Allocation | Internal solver calls |
| --- | --- | --- | --- | --- | --- | --- | --- |
| One week | 20 | 16/16 | 4/4 | 20/20 | 20.001169834987554 | 21 | 55 |
| Three weeks | 20 | 16/16 | 4/4 | 20/20 | 120.00555450856191 | 122 | 76 |

Every execution stayed within its allocation. All forty status, objective and
decision fingerprints match the frozen baseline. Infeasibility is counted
separately from numeric equality. The one-week unproved result remains unproved;
this replay does not upgrade its evidence or alter the frozen value.

The local queue setup records actual allocations and receipts. It is measurement
bookkeeping, not a claim that this script serves the public football-bundle API.
The separate admission replay and API tests exercise submission and orchestration.
There were zero network calls. Source, input and baseline hashes, actual solve
records and per-job work receipts are retained in the JSON record. No work limit,
accounting tolerance or Phase 1 artifact changed.
