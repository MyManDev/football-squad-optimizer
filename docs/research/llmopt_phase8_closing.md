# LLMOPT local workload and closing report

The fresh comparison opened 80 to 0 at 1 week and 80 to 40 at 3 weeks. Each count covers the same twenty frozen member-weeks with the same three preferences. Each mode also repeats every run against its own warm cache. [Per-run measurements](llmopt_phase8_load.json)

## Work and elapsed time

| Weeks | Release | Cache | Server jobs | Server solver calls | Device workers | Device solver calls | Total seconds p50 / p95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | off | cold | 80 | 240 | 0 | 0 | 11.817 / 12.418 |
| 1 | on | cold | 0 | 0 | 40 | 1020 | 5.597 / 14.626 |
| 1 | off | warm | 0 | 0 | 0 | 0 | 0.026 / 0.036 |
| 1 | on | warm | 0 | 0 | 0 | 0 | 0.011 / 0.018 |
| 3 | off | cold | 80 | 320 | 0 | 0 | 175.395 / 256.057 |
| 3 | on | cold | 40 | 320 | 0 | 0 | 176.527 / 262.973 |
| 3 | off | warm | 0 | 0 | 0 | 0 | 0.038 / 0.055 |
| 3 | on | warm | 0 | 0 | 0 | 0 | 0.045 / 0.091 |

The two individual prices can wait together in the real file queue. One local worker drains them, then the combined stage can start. Every queue wait runs from durable publication to successful claim. Worker time runs from claim through terminal result. Total time includes capability lookup, admission, solver work, result reads and local process communication. An arm with zero jobs has no per-job sample.

| Weeks | Release | Cache | Queue seconds p50 / p95 | Worker seconds p50 / p95 | CP units/job p50 / p95 | Solver calls/job p50 / p95 | Device seconds p50 / p95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | off | cold | 0.019 / 3.026 | 2.828 / 3.280 | 1.002 / 1.791 | 3.000 / 3.000 | n/a |
| 1 | on | cold | n/a | n/a | n/a | n/a | 1.775 / 10.406 |
| 1 | off | warm | n/a | n/a | n/a | n/a | n/a |
| 1 | on | warm | n/a | n/a | n/a | n/a | n/a |
| 3 | off | cold | 0.019 / 69.914 | 45.681 / 77.558 | 22.728 / 60.009 | 4.000 / 4.000 | n/a |
| 3 | on | cold | 0.016 / 0.023 | 68.390 / 187.787 | 45.492 / 107.121 | 8.000 / 12.000 | n/a |
| 3 | off | warm | n/a | n/a | n/a | n/a | n/a |
| 3 | on | warm | n/a | n/a | n/a | n/a | n/a |

CP units are measured deterministic solver work. Native HiGHS and device HiGHS have separate wall limits. Per-job receipts retain measured native seconds and calls, CP seconds and units, and configured allocations when supplied. Device worker rows retain actual WASM calls, solve times and load time. Local elapsed values describe this single-worker replay. The median and nearest-rank p95 describe independent cases within each row.

| Weeks | Release | Warm runs matching cold | Existing jobs returned | New warm jobs | New warm device workers |
| --- | --- | --- | --- | --- | --- |
| 1 | off | 20 / 20 | 0 | 0 | 0 |
| 1 | on | 20 / 20 | 0 | 0 | 0 |
| 3 | off | 20 / 20 | 0 | 0 | 0 |
| 3 | on | 20 / 20 | 0 | 0 | 0 |

Warm confirmation repeats the same draft against its own completed or failed run. The comparison covers each slot's outcome, reason, source, expected net points and transfer path. Returning an existing terminal job does not create a queue entry.

## Alternative yield and paired scores

| Weeks | Release | Cache | Completed / possible preference results | Distinct additional paths | Runs yielding another path |
| --- | --- | --- | --- | --- | --- |
| 1 | off | cold | 60 / 60 | 3 | 3 / 20 |
| 1 | on | cold | 60 / 60 | 3 | 3 / 20 |
| 1 | off | warm | 60 / 60 | 3 | 3 / 20 |
| 1 | on | warm | 60 / 60 | 3 | 3 / 20 |
| 3 | off | cold | 60 / 60 | 10 | 9 / 20 |
| 3 | on | cold | 60 / 60 | 10 | 9 / 20 |
| 3 | off | warm | 60 / 60 | 10 | 9 / 20 |
| 3 | on | warm | 60 / 60 | 10 | 9 / 20 |

The three preference result slots comprise the two individual prices and the combined plan. A completed price may return the same transfers as the base or another price. The yield column counts unique transfer and chip paths across the whole window after removing those duplicates and the base. These are the alternatives in this pricing workload. Separate hard-only menus and package-search experiments use other workloads.

| Weeks | Result | Paired / total | Same transfer path | Higher | Equal | Lower | Total expected net difference |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | base | 20 / 20 | 20 | 0 | 20 | 0 | +0.000 |
| 1 | combined | 20 / 20 | 20 | 0 | 20 | 0 | +0.000 |
| 3 | base | 20 / 20 | 20 | 0 | 20 | 0 | +0.000 |
| 3 | combined | 20 / 20 | 20 | 0 | 20 | 0 | +0.000 |

Score differences use enabled minus disabled published expected net points. Transfer identity excludes changes confined to the lineup or captain. The equal-score count uses an absolute numerical comparison of 1e-8 points. Incomplete pairs keep their status in the row record and contribute no numeric difference.

## Phase 1 reference

| Member-week | Weeks | Server jobs | Solver calls | Solver seconds |
| --- | --- | --- | --- | --- |
| gw8-313686 | 1 | 4 | 12 | 7.647 |
| gw8-313686 | 3 | 4 | 16 | 45.255 |
| gw9-313686 | 1 | 4 | 12 | 8.709 |
| gw9-313686 | 3 | 4 | 16 | 100.327 |

Phase 1 froze all twenty member-weeks. It measured this complete four-job workload for the first member of each capture only. Its solver timings and isolated queue counts did not include API orchestration. The fresh disabled arm extends the same two unbounded keep preferences and unbounded no-hit preference over the full twenty. The original rotated standalone controls serve another purpose and were not substituted for those three preferences. [Phase 1 baseline](llmopt_phase1_baseline.md)

## Package search

| Full-pool arm | Computed / total | Accepted packages | Raw XI gain | Expected lineup net gain | Selection utility gain |
| --- | --- | --- | --- | --- | --- |
| disabled | 18 / 20 | 0 | +0.000 | +0.000 | +0.000 |
| packages | 18 / 20 | 0 | +0.000 | +0.000 | +0.000 |
| opened_gate | 18 / 20 | 0 | +0.000 | +0.000 | +0.000 |

The separate Phase 6 record counts all twenty member-weeks. Numeric gains cover the completed pairs only. Sixteen full-pool proposals produced zero accepted packages. Both package settings remain at their default value of zero. [Full-pool comparison](llmopt_phase6_results.md)

## Reproduction and scope

Run the commands from the repository root with its Python environment and installed web dependencies. Use a local checkout containing both publication commits listed in the frozen inputs. The frozen inputs and Phase 1 records are read-only.

```powershell
$env:PYTHONPATH='src'
python -m docs.research.llmopt_phase8.measure
python -m docs.research.llmopt_phase8.report
```

Measured source commit `5813b8832f3a9799c877756cef4e4e4aa32068a5`. The JSON also records source digests. The server parses each isolated configuration through its normal environment reader. The local API advertises the capability to the production planner. The measured transport submits the resulting production requests via an in-process FastAPI adapter. For the enabled one-week draft, every new device worker requires another matching capability response. Each new worker records its permission read number. The server retains its legacy cache reader in both modes. The local solver uses the original published table and member documents, verified against the frozen solver inputs. Only the worker message port, browser session-storage medium and HTTP connection are adapted for local replay. Each asset loads locally.

Cold arms start with independent empty queues, caches and storage. Warm arms rebuild the device client while retaining the same run identity and stored results. Runs use the original member inputs and the saved expected-point table. No deployment, live traffic, load from unrelated users, provider call, historical realized-score comparison or live-latency measurement forms part of this experiment.

## Unfinished

The Phase 6 full-pool record retains accounting failures for gw8-3832237 and gw9-3832237. Its disabled main solve for gw8-5349883 used 122.000084823223 units against 122. The cap and tolerance are unchanged. The paired package result still covers 18 of 20 cases. [Original probe](llmopt_window_budget_probe.md)

All four answer slots completed in every measured workload pass.

The release setting defaults to disabled. The project owner decides whether and when to activate it. [Release decision](../architecture/decisions/0024-llmopt-release-control.md)
