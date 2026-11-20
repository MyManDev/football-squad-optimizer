# LLMOPT local workload and closing report

The fresh comparison opened 80 to 0 at 1 week and 80 to 40 at 3 weeks. Each count covers the same twenty frozen member-weeks with the same three preferences. Each mode also repeats every run against its own warm cache. [Per-run measurements](llmopt_phase8_load.json)

## Comparison with the previous workload

The previous record comes from Git commit `d9a99fa421fda5ee27b735f969940597da61f6d3` and identifies measured producer `5813b8832f3a9799c877756cef4e4e4aa32068a5`. H2 measures producer `2fd62c15395c707ca7fe1d7986bf49f30b4350ac` on the same frozen inputs. Both records cover 640 answer slots across twenty member-weeks, two windows, two release modes and cold and warm caches. [Previous measurement](https://github.com/MyManDev/football-squad-optimizer/blob/d9a99fa421fda5ee27b735f969940597da61f6d3/docs/research/llmopt_phase8_load.json)

| Weeks | Release | Cache | Slots | Exact answers | Same status and reason | Both completed | Same path and points | Source, earlier → H2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | off | cold | 80 | 80 | 80 | 80 | 80 | api-cache → api-cache (80) |
| 1 | on | cold | 80 | 80 | 80 | 80 | 80 | device → device (80) |
| 1 | off | warm | 80 | 80 | 80 | 80 | 80 | api-cache → api-cache (80) |
| 1 | on | warm | 80 | 80 | 80 | 80 | 80 | device → device (80) |
| 3 | off | cold | 80 | 80 | 80 | 80 | 80 | api-cache → api-cache (80) |
| 3 | on | cold | 80 | 80 | 80 | 80 | 80 | api-cache → api-cache (80) |
| 3 | off | warm | 80 | 80 | 80 | 80 | 80 | api-cache → api-cache (80) |
| 3 | on | warm | 80 | 80 | 80 | 80 | 80 | api-cache → api-cache (80) |

Exact answers include every recorded field. Successful answers carry solver status, source, full-window transfers and chip use, and expected net points. Failed or idle slots carry their recorded status and reason and contribute no plan or score. The path-and-points column requires a completed pair, the same transfer and chip path and an absolute difference of at most 1e-8 points. The historical record omits lineups, captain choices and bank balances.

### Queue and worker time

| Weeks | Release | Cache | Record | Jobs | Queue p50 / p95 (s) | Queue max (s), member-week and stage | Worker p50 / p95 (s) | Worker max (s), member-week and stage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | off | cold | Earlier | 80 | 0.019 / 3.026 | 3.395 (gw8-5081114, individual_prices) | 2.828 / 3.280 | 3.760 (gw8-2281624, combined) |
| 1 | off | cold | H2 | 80 | 0.012 / 2.980 | 3.932 (gw9-5662073, individual_prices) | 2.816 / 3.389 | 3.903 (gw9-5662073, individual_prices) |
| 1 | on | cold | Earlier | 0 | n/a | n/a | n/a | n/a |
| 1 | on | cold | H2 | 0 | n/a | n/a | n/a | n/a |
| 1 | off | warm | Earlier | 0 | n/a | n/a | n/a | n/a |
| 1 | off | warm | H2 | 0 | n/a | n/a | n/a | n/a |
| 1 | on | warm | Earlier | 0 | n/a | n/a | n/a | n/a |
| 1 | on | warm | H2 | 0 | n/a | n/a | n/a | n/a |
| 3 | off | cold | Earlier | 80 | 0.019 / 69.914 | 82.485 (gw9-3832237, individual_prices) | 45.681 / 77.558 | 84.388 (gw9-6879786, base) |
| 3 | off | cold | H2 | 80 | 0.015 / 66.074 | 82.158 (gw9-5662073, individual_prices) | 45.947 / 73.004 | 82.145 (gw9-5662073, individual_prices) |
| 3 | on | cold | Earlier | 40 | 0.016 / 0.023 | 0.032 (gw9-3832237, base) | 68.390 / 187.787 | 207.491 (gw9-2199732, preference_bundle) |
| 3 | on | cold | H2 | 40 | 0.009 / 0.016 | 0.018 (gw9-3832237, base) | 68.645 / 192.386 | 211.677 (gw9-2199732, preference_bundle) |
| 3 | off | warm | Earlier | 0 | n/a | n/a | n/a | n/a |
| 3 | off | warm | H2 | 0 | n/a | n/a | n/a | n/a |
| 3 | on | warm | Earlier | 0 | n/a | n/a | n/a | n/a |
| 3 | on | warm | H2 | 0 | n/a | n/a | n/a | n/a |

Each queue publication contributes one wait and one worker duration. An arm with zero new server jobs has no per-job observations.

### Change in elapsed time

| Weeks | Cache | Seconds p50 / p95 | H2 off | H2 on | H2 on minus off | Earlier on | H2 on minus earlier on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cold | Run | 11.497 / 12.487 | 5.752 / 15.122 | -5.745 / +2.635 | 5.597 / 14.626 | +0.155 / +0.496 |
| 1 | cold | Worker per job | 2.816 / 3.389 | n/a | n/a | n/a | n/a |
| 1 | warm | Run | 0.015 / 0.033 | 0.013 / 0.020 | -0.003 / -0.013 | 0.011 / 0.018 | +0.002 / +0.002 |
| 1 | warm | Worker per job | n/a | n/a | n/a | n/a | n/a |
| 3 | cold | Run | 172.700 / 260.216 | 173.435 / 259.871 | +0.735 / -0.345 | 176.527 / 262.973 | -3.092 / -3.102 |
| 3 | cold | Worker per job | 45.947 / 73.004 | 68.645 / 192.386 | +22.698 / +119.382 | 68.390 / 187.787 | +0.255 / +4.598 |
| 3 | warm | Run | 0.029 / 0.043 | 0.040 / 0.069 | +0.011 / +0.027 | 0.045 / 0.091 | -0.005 / -0.021 |
| 3 | warm | Worker per job | n/a | n/a | n/a | n/a | n/a |

Run durations cover the entire member workload. Worker durations cover one server job. Signed columns compare the median and nearest-rank p95 within each arm. Positive values indicate longer elapsed time.

## Workload checks

All 320 OFF answers exactly matched the previous record. All 160 cross-mode base and combined pairs completed with matching transfer paths and net points. All 80 warm runs matched cold answers with zero new server jobs or device workers.

## Work and elapsed time

| Weeks | Release | Cache | Server jobs | Server solver calls | Device workers | Device solver calls | Total seconds p50 / p95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | off | cold | 80 | 240 | 0 | 0 | 11.497 / 12.487 |
| 1 | on | cold | 0 | 0 | 40 | 1020 | 5.752 / 15.122 |
| 1 | off | warm | 0 | 0 | 0 | 0 | 0.015 / 0.033 |
| 1 | on | warm | 0 | 0 | 0 | 0 | 0.013 / 0.020 |
| 3 | off | cold | 80 | 320 | 0 | 0 | 172.700 / 260.216 |
| 3 | on | cold | 40 | 320 | 0 | 0 | 173.435 / 259.871 |
| 3 | off | warm | 0 | 0 | 0 | 0 | 0.029 / 0.043 |
| 3 | on | warm | 0 | 0 | 0 | 0 | 0.040 / 0.069 |

The two individual prices can wait together in the real file queue. One local worker drains them, then the combined stage can start. Every queue wait runs from durable publication to successful claim. Worker time runs from claim through terminal result. Total time includes capability lookup, admission, solver work, result reads and local process communication. An arm with zero jobs has no per-job sample.

| Weeks | Release | Cache | Queue seconds p50 / p95 | Worker seconds p50 / p95 | CP units/job p50 / p95 | Solver calls/job p50 / p95 | Device seconds p50 / p95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | off | cold | 0.012 / 2.980 | 2.816 / 3.389 | 1.002 / 1.791 | 3.000 / 3.000 | n/a |
| 1 | on | cold | n/a | n/a | n/a | n/a | 1.758 / 10.063 |
| 1 | off | warm | n/a | n/a | n/a | n/a | n/a |
| 1 | on | warm | n/a | n/a | n/a | n/a | n/a |
| 3 | off | cold | 0.015 / 66.074 | 45.947 / 73.004 | 22.728 / 60.009 | 4.000 / 4.000 | n/a |
| 3 | on | cold | 0.009 / 0.016 | 68.645 / 192.386 | 45.492 / 107.121 | 8.000 / 12.000 | n/a |
| 3 | off | warm | n/a | n/a | n/a | n/a | n/a |
| 3 | on | warm | n/a | n/a | n/a | n/a | n/a |

CP units are measured deterministic solver work. Native HiGHS and device HiGHS have separate wall limits. Per-job receipts retain measured native seconds and calls, CP seconds and units, and configured allocations when supplied. Device worker rows retain actual WASM calls, solve times and load time. Local elapsed values describe this single-worker replay. Run percentiles use the twenty member-weeks in an arm. Per-job and per-worker percentiles use the individual jobs and workers.

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

| Weeks | Cache | Result | Both completed / total | Same transfer path | Same path and points | Higher | Equal | Lower | Total expected net difference | Source, off → on |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cold | base | 20 / 20 | 20 | 20 | 0 | 20 | 0 | +0.000 | api-cache → device (20) |
| 1 | cold | combined | 20 / 20 | 20 | 20 | 0 | 20 | 0 | +0.000 | api-cache → device (20) |
| 1 | warm | base | 20 / 20 | 20 | 20 | 0 | 20 | 0 | +0.000 | api-cache → device (20) |
| 1 | warm | combined | 20 / 20 | 20 | 20 | 0 | 20 | 0 | +0.000 | api-cache → device (20) |
| 3 | cold | base | 20 / 20 | 20 | 20 | 0 | 20 | 0 | +0.000 | api-cache → api-cache (20) |
| 3 | cold | combined | 20 / 20 | 20 | 20 | 0 | 20 | 0 | +0.000 | api-cache → api-cache (20) |
| 3 | warm | base | 20 / 20 | 20 | 20 | 0 | 20 | 0 | +0.000 | api-cache → api-cache (20) |
| 3 | warm | combined | 20 / 20 | 20 | 20 | 0 | 20 | 0 | +0.000 | api-cache → api-cache (20) |

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
python -m docs.research.llmopt_phase8.report --check --compare-ref d9a99fa421fda5ee27b735f969940597da61f6d3
```

Measured source commit `2fd62c15395c707ca7fe1d7986bf49f30b4350ac`. The JSON also records source digests. The server parses each isolated configuration through its normal environment reader. The local API advertises the capability to the production planner. The measured transport submits the resulting production requests via an in-process FastAPI adapter. For the enabled one-week draft, every new device worker requires another matching capability response. Each new worker records its permission read number. The server retains its legacy cache reader in both modes. The local solver uses the original published table and member documents, verified against the frozen solver inputs. Only the worker message port, browser session-storage medium and HTTP connection are adapted for local replay. Each asset loads locally.

Cold arms start with independent empty queues, caches and storage. Warm arms rebuild the device client while retaining the same run identity and stored results. Runs use the original member inputs and the saved expected-point table. No deployment, live traffic, load from unrelated users, provider call, historical realized-score comparison or live-latency measurement forms part of this experiment.

## Unfinished

The Phase 6 full-pool record retains accounting failures for gw8-3832237 and gw9-3832237. Its disabled main solve for gw8-5349883 used 122.000084823223 units against 122. The cap and tolerance are unchanged. The paired package result still covers 18 of 20 cases. [Original probe](llmopt_window_budget_probe.md)

A separate develop-based change returned feasible three-week plans for both five-transfer cases and preserved the other eighteen on the frozen expected-window workload. The Phase 6 package comparison above uses its original measurements. [Independent before-and-after record](https://github.com/MyManDev/football-squad-optimizer/blob/fc2a6d9c4931d8da25df0b272dcf8211f4574429/docs/research/expected_window_guard.md) · [Pull request #1478](https://github.com/MyManDev/football-squad-optimizer/pull/1478)

All four answer slots completed in every measured workload pass.

The release setting defaults to disabled. The project owner decides whether and when to activate it. [Release decision](../architecture/decisions/0024-llmopt-release-control.md)

Provider acceptance is a separate owner check. The local workload made no provider calls. [One-message checks for each provider](llmopt_provider_acceptance.md)
