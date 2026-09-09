# Advice capacity: local synthetic acceptance

Measured on 9 September 2026 UTC (10 September local time). The machine-readable
[record](advice_capacity_20260909.json) includes each request outcome and response digest, source inventory,
capture identity and process resource result. All 18 scenarios completed successfully.
Deduplicated bursts returned one job and byte-identical answers; cache-hit bursts created
no jobs; distinct bursts created exactly one job per request.

| Workers | Users | Scenario | Submit p95 (s) | Complete p95 (s) | Sampled queue peak | API peak RSS (MiB) | Worker peak RSS (MiB, each) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 15 | dedup | 0.111 | 0.429 | 0 | 197.8 | 184.2 |
| 1 | 15 | distinct | 0.461 | 1.735 | 11 | 200.1 | 184.9 |
| 1 | 15 | cache-hit | 0.072 | 0.073 | 0 | 198.9 | 185.6 |
| 1 | 30 | dedup | 0.189 | 0.314 | 0 | 198.4 | 184.4 |
| 1 | 30 | distinct | 0.975 | 3.066 | 21 | 204.8 | 185.5 |
| 1 | 30 | cache-hit | 0.094 | 0.095 | 0 | 204.2 | 186.4 |
| 1 | 60 | dedup | 0.301 | 0.479 | 0 | 199.7 | 184.6 |
| 1 | 60 | distinct | 1.940 | 6.410 | 47 | 210.0 | 187.1 |
| 1 | 60 | cache-hit | 0.166 | 0.167 | 0 | 207.8 | 186.4 |
| 3 | 15 | dedup | 0.141 | 0.229 | 0 | 196.3 | 177.2, 177.1, 184.4 |
| 3 | 15 | distinct | 0.791 | 0.969 | 2 | 197.6 | 184.3, 184.4, 185.0 |
| 3 | 15 | cache-hit | 0.047 | 0.048 | 0 | 197.7 | 184.7, 185.1, 185.3 |
| 3 | 30 | dedup | 0.201 | 0.280 | 0 | 197.4 | 177.2, 184.1, 177.8 |
| 3 | 30 | distinct | 1.657 | 2.022 | 0 | 202.2 | 185.5, 184.5, 185.4 |
| 3 | 30 | cache-hit | 0.120 | 0.121 | 0 | 203.6 | 185.0, 185.2, 184.9 |
| 3 | 60 | dedup | 0.321 | 0.454 | 0 | 198.7 | 184.2, 177.0, 177.2 |
| 3 | 60 | distinct | 3.899 | 4.675 | 0 | 208.1 | 185.2, 185.9, 186.0 |
| 3 | 60 | cache-hit | 0.210 | 0.211 | 0 | 209.5 | 186.1, 186.0, 186.2 |

## Interpretation

The probe establishes the local request/queue/worker/cache path under bursts. It does
not select a production replica count. Use the same probe against the prepared host
with its real resource limits and representative captured roster before setting a
latency target. More workers also contend for shared queue metadata; their benefit
must be measured rather than assumed to scale linearly.

- Local shared Windows development host, no dedicated CPU quota; not a production replica decision.
- One burst per scenario/configuration; no confidence interval or sustained-load claim.
- Rate limit 5000 and worker idle poll 0.05 seconds are measurement configuration, not production defaults.
- Queue depth is periodically sampled through the API; zero can miss a short queue.
- Role resources include Windows venv launcher and descendants; peak RSS sums their working sets, not physical unique memory.
- API and worker resources exclude the load generator; startup after API readiness may be included for workers.
- Private production inputs, remote volumes, server resource limits and real-roster solver costs were not exercised.
- All six per-case Python source inventories are identical and match final source; Git metadata commits do not change those bytes.

The first run exposed two product defects. A POST with an earlier cache miss could
enqueue again after completion, and Windows polling handles could deny terminal
replacement. Controlled regressions reproduced both; the existing metadata lock now
covers final cache admission and polling reads. The 70 focused queue/API/worker tests
passed after those fixes. No ledger workaround or retry-until-green loop was added.
The second run passed functionally but measured launcher resources incorrectly;
the third run then exposed a pre-lock timestamp that could stop a worker. The clock now
runs after lock acquisition, with backwards-time rejection retained and 88 focused tests
passing. This fourth run measures complete owned process trees with those fixes. Earlier
receipts are retained.

## Reproduce

Install the `api`, `dev` and `capacity` extras in the pinned Python 3.13 environment.
The opt-in test is offline and creates synthetic captures plus fresh stores:

```powershell
$env:SQUADOPT_CAPACITY_PROBE='1'
.venv/Scripts/python -m pytest tests/integration/test_advice_capacity.py -q -p no:cacheprovider --basetemp .pt/capacity-new-run
```

Each case writes `capacity.json` beside API/worker logs. Use a new output root.
For a configured deployment, `python -m squadopt.platform.advice_load --help` exposes
the HTTP-only probe. Supply explicit request coordinates and a new report path.
Warm a cache-hit dataset explicitly; the command never hides warmup or retries failures.
