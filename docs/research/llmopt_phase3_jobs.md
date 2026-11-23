# One preference job on twenty frozen member-weeks

At three weeks, **10 of 20 member-weeks completed all three priority layers**, including
**10 of the 16 with a feasible main plan**. Four other feasible runs completed one layer
and two completed two. In the remaining four member-weeks, contradictory hard rules
prevented a main plan, so no preference job started. The one-week solver completed
all three layers in all 16 eligible runs. [Machine-readable record](llmopt_phase3_jobs.json)

## Priority layers and work

Each program gave one preference to each priority and allowed 1.5 points of total
concession. A layer counts as complete when its maximum number of satisfied rules
has been proved. A proved count can be zero. Only rules from completed layers can
be classified as satisfied or left out. Rules from uncompleted layers are recorded
as unsearched, even if the selected plan happens to satisfy them.

| Weeks | Completed all three / all member-weeks | Completed all three / eligible | Completed 0 / 1 / 2 / 3 layers among eligible | Satisfied rules | Left out | Unsearched |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 16/20 | 16/16 | 0 / 0 / 0 / 16 | 45 | 3 | 0 |
| 3 | 10/20 | 10/16 | 0 / 4 / 2 / 10 | 33 | 5 | 10 |

The 16 eligible runs at each window received a single preference job each. The ledger
charges measured CP work plus the reserved native work. Native units are reservations
and do not measure elapsed time. The table includes only those preference jobs.
Main-job receipts for the four contradictory cases and all legacy pricing work are
accounted for separately in the JSON.

| Weeks | Units per preference job | Total available | CP used | Native reserved | Total charged | Charged / available | Min / median / max charged per job |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 63 | 1,008 | 22.366716274 | 0 | 22.366716274 | 2.22% | 1.265 / 1.384 / 1.675 |
| 3 | 366 | 5,856 | 2,644.991671485 | 16 | 2,660.991671485 | 45.44% | 8.372 / 197.777 / 293.318 |

### Three-week outcomes by member-week

The six partial programs set `budget_exhausted`. The job receipt records the amount
charged and the returned result records the last completed layer. The replay does
not store individual count and points passes or their stop reasons.

| Member-week | Completed layers | Unsearched rules | CP used | Native reserved |
| --- | --- | --- | --- | --- |
| gw8-313686 | 3 | 0 | 45.062 | 1 |
| gw8-2199732 | 2 | 1 | 288.939 | 1 |
| gw8-2281624 | 3 | 0 | 26.258 | 1 |
| gw8-3832237 | 1 | 2 | 287.587 | 1 |
| gw8-5081114 | 3 | 0 | 58.581 | 1 |
| gw8-5349883 | 1 | 2 | 284.845 | 1 |
| gw8-5662073 | 3 | 0 | 7.372 | 1 |
| gw8-6654210 | 1 | 2 | 292.318 | 1 |
| gw9-313686 | 3 | 0 | 7.610 | 1 |
| gw9-2199732 | 3 | 0 | 243.870 | 1 |
| gw9-2281624 | 2 | 1 | 276.032 | 1 |
| gw9-3832237 | 1 | 2 | 289.721 | 1 |
| gw9-5081114 | 3 | 0 | 77.215 | 1 |
| gw9-5349883 | 3 | 0 | 218.579 | 1 |
| gw9-5662073 | 3 | 0 | 66.027 | 1 |
| gw9-6654210 | 3 | 0 | 174.975 | 1 |

`gw8-4287206`, `gw8-6879786`, `gw9-4287206` and `gw9-6879786` returned
`PLAN_NOT_FOUND` at both windows. Their preference allocation was zero.

The previous record in commit `4f9ad7ff7442ef1fa1a8fade1c6daa33f5f1689c`
showed three complete layers for 9/20 overall and 9/16 eligible at three weeks.
Preference jobs then used 822.946352998 CP units plus 16 native units from the
same 5,856 units available. Four member-weeks changed their number of complete
layers. `gw8-5349883` went from zero to one, and `gw9-5081114` and
`gw9-6654210` each went from one to three. The Free Hit case `gw9-2281624`
went from three to two. It used 276.031935308 CP units plus one native unit
from its 366-unit allocation. Its third-priority rule to keep player `466075`
was unsearched. One-week completion counts were unchanged.

## Server jobs and repeated requests

| Weeks | Preference mode | Runs | Main cache hits | Main plans infeasible | Jobs admitted | Max jobs per run | Max charge in any job |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | legacy_prices | 20 | 0 | 4 | 36 | 2 | 2.816995632 |
| 1 | priority_total | 20 | 16 | 4 | 20 | 1 | 1.675151352 |
| 3 | legacy_prices | 20 | 0 | 4 | 36 | 2 | 335.901700784 |
| 3 | priority_total | 20 | 16 | 4 | 20 | 1 | 293.317837289 |

The two windows and two modes produced 80 run records and admitted 112 jobs in
total. Every job stayed within its allocation. Legacy mode started cold and ran
the main plan, both individual prices and the selected combination in at most two
jobs. Total mode reused the completed main when available. A preference layer
never opened a new server job. Each of the four groups repeated 48 requests after
rebuilding the service. All 192 repeats returned cached answers and opened zero
additional jobs.

## Reproduction

Run `python -m docs.research.llmopt_phase3.measure` separately from tests and CI.
The producer was `8a8da017d7068e1682117b04ac64215358355d07` with the release
setting enabled. The local public API, durable admission, immutable requests,
real worker and solvers used the frozen Phase 1 point tables for gameweeks 8 and 9.
The run used replay-specific chip rights and timestamps and made zero live network
requests. No forecasting, scoring, tests or CI ran with the measurement. The
normalized Phase 1 input manifest SHA-256 is
`fdbd303a04679d1b866f366c56b72cf0fe056b6e9f52c2ed752f0ae88d0032fc`.

The fixed-decision certificate recomputes the main objective from the retained
plan and preserves its proof status. Count searches and the points tie break share
the admitted preference allocation. The one- and three-week run limits are 84
and 488 units. The independent tiny-model enumeration and cold main-plus-preference
worker coverage live in `tests/unit/test_priority_preferences.py` and
`tests/unit/test_llmopt_preference_bundle.py`. [ADR 0019](../architecture/decisions/0019-llmopt-priority-budget.md)
