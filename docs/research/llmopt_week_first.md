# One-week release on twenty frozen member-weeks

Measured source `f19e6afa6ab24b82034a075d2399179684f091e2`. The mixed setting enables the one-week workflow and leaves the separate three-week setting disabled. Both package settings and the three-week path setting retain their defaults. H2 measured source `2fd62c15395c707ca7fe1d7986bf49f30b4350ac`. [Raw measurements](llmopt_week_first.json) · [H2 comparison](llmopt_phase8_closing.md)

## Mixed workload and historical slots

| Weeks | Matching H2 arm | Cache | Slots | Same status/reason | Same source | Same path | Same net | All fields exact | Server jobs | Device workers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | on | cold | 80 | 80 | 80 | 80 | 80 | 80 | 0 | 40 |
| 1 | on | warm | 80 | 80 | 80 | 80 | 80 | 80 | 0 | 0 |
| 3 | off | cold | 80 | 80 | 80 | 80 | 80 | 80 | 80 | 0 |
| 3 | off | warm | 80 | 80 | 80 | 80 | 80 | 80 | 0 | 0 |

Each member contributed the base, two individual prices and the combined plan. Transfer paths include chip use. The points column uses the historical absolute tolerance of 1e-8. Exact matches include every field recorded on the original answer slot. H2 did not record individual lineup decisions. The transport comparison includes stage order, submission result, public method, route, status and counts of real publications and workers. Job-specific status paths are compared without their generated identifiers.

| Weeks | Cache | H2 complete p50 / p95 (s) | Mixed complete p50 / p95 (s) |
| --- | --- | --- | --- |
| 1 | cold | 5.752 / 15.122 | 4.445 / 9.575 |
| 1 | warm | 0.013 / 0.020 | 0.007 / 0.010 |
| 3 | cold | 172.700 / 260.216 | 98.265 / 150.939 |
| 3 | warm | 0.029 / 0.043 | 0.019 / 0.021 |

## Time to a visible main plan in Chromium

| Cache | Release | Member-weeks | Visible main p50 / p95 (s) | Complete p50 / p95 (s) | Server jobs | Browser device workers |
| --- | --- | --- | --- | --- | --- | --- |
| cold | off | 20 | 2.079 / 4.095 | 12.173 / 12.283 | 80 | 0 |
| cold | mixed | 20 | 0.620 / 1.948 | 4.400 / 9.470 | 0 | 40 |
| warm | off | 20 | 0.406 / 0.419 | 0.406 / 0.419 | 0 | 0 |
| warm | mixed | 20 | 0.413 / 0.431 | 0.413 / 0.431 | 0 | 0 |

Cold samples start at the Compute click. Warm samples reload the confirmed run in the same tab. Both use the production page, its normal job polling, the original member and capture publications, and local server or device solvers. The page uses the capture date for deadline decisions. At each animation frame the observer checks the completed base card. It scrolls its first populated calculated value fully into the 1280 by 900 viewport when needed and verifies that value's visibility and opacity. Completion records the first frame with the completed combined card in the document. Both visible decisions are checked against the H2 chip and held squad after transfers. The worker count comes from the browser. Each warm restore must reuse its cached results without starting a worker or publishing a server job. Only Date is fixed for deadline decisions. Navigation, performance timing, animation frames and timers use Chromium's native clock. The recording also verifies that each pass finishes inside the independent monotonic interval observed by the browser driver. The median and the nearest-rank 95th percentile over 20 samples are reported independently for each arm.

### Members and stages at the one-week total-time tail

The H2 one-week cold p95 was gw8-3832237. Its base worker took 2.009 s over 16 solves, and the preference worker took 13.079 s over 64 solves. The H2 one-week cold maximum was gw9-5662073. Its base worker took 2.464 s over 8 solves, and the preference worker took 22.587 s over 32 solves. The mixed browser cold p95 was gw8-3832237. Its main plan appeared at 1.948 s and its combined plan completed 7.522 s later. The mixed browser cold maximum was gw9-5662073. Its main plan appeared at 2.445 s and its combined plan completed 12.603 s later.

| Member-week | Cache | Release | Rank | Main visible (s) | Complete (s) | After main (s) | H2 complete (s) | Current stage time (s) | H2 worker time (s), calls in parentheses |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gw9-3832237 | cold | off | browser p95 | 2.082 | 12.283 | 10.202 | 12.094 | base 1.489, individual_prices 1.404, individual_prices 1.462, combined 1.469 | base 2.835 (3), individual_prices 2.985 (3), individual_prices 2.905 (3), combined 2.951 (3) |
| gw8-6879786 | cold | off | browser max | 2.097 | 12.330 | 10.233 | 11.733 | base 1.526, individual_prices 1.406, individual_prices 1.554, combined 1.295 | base 3.068 (3), individual_prices 2.913 (3), individual_prices 3.035 (3), combined 2.571 (3) |
| gw9-5081114 | cold | off | H2 p95 | 4.095 | 12.197 | 8.102 | 12.487 | base 1.814, individual_prices 1.330, individual_prices 1.365, combined 1.536 | base 3.596 (3), individual_prices 2.830 (3), individual_prices 2.759 (3), combined 3.138 (3) |
| gw9-5662073 | cold | off | H2 max | 4.096 | 12.197 | 8.101 | 14.247 | base 1.655, individual_prices 2.051, individual_prices 1.585, combined 1.875 | base 3.357 (3), individual_prices 3.903 (3), individual_prices 3.230 (3), combined 3.586 (3) |
| gw8-3832237 | cold | mixed | browser p95, H2 p95 | 1.948 | 9.470 | 7.522 | 15.122 | base 1.951, preference_bundle 7.600 | base 2.009 (16), preferences 13.079 (64) |
| gw9-5662073 | cold | mixed | browser max, H2 max | 2.445 | 15.047 | 12.603 | 25.081 | base 2.463, preference_bundle 12.768 | base 2.464 (8), preferences 22.587 (32) |
| gw8-2199732 | warm | off | browser p95 | 0.419 | 0.419 | 0.000 | 0.014 | cached | cached |
| gw8-313686 | warm | off | browser max | 0.423 | 0.423 | 0.000 | 0.014 | cached | cached |
| gw9-5662073 | warm | off | H2 p95 | 0.406 | 0.406 | 0.000 | 0.033 | cached | cached |
| gw8-6879786 | warm | off | H2 max | 0.406 | 0.406 | 0.000 | 0.034 | cached | cached |
| gw8-6654210 | warm | mixed | browser p95 | 0.431 | 0.431 | 0.000 | 0.010 | base 0.000, preference_bundle 0.001 | cached |
| gw8-313686 | warm | mixed | browser max | 0.443 | 0.443 | 0.000 | 0.012 | base 0.000, preference_bundle 0.001 | cached |
| gw9-2281624 | warm | mixed | H2 p95 | 0.409 | 0.409 | 0.000 | 0.020 | base 0.000, preference_bundle 0.001 | cached |
| gw8-6879786 | warm | mixed | H2 max | 0.400 | 0.400 | 0.000 | 0.022 | base 0.000, preference_bundle 0.001 | cached |

Current mixed stage times come from the separate in-process transport replay. Current disabled stages use the actual browser run's server worker times. The browser total also includes page scheduling, polling, rendering and, on reload, navigation. H2 recorded complete transport latency and worker time. It did not measure first paint. Cached returns use no worker. These are local samples on one machine.

## Reproduce

```powershell
$env:PYTHONPATH='src'
python -m docs.research.llmopt_week_first.measure --resume
python -m docs.research.llmopt_week_first.report --check
```

Run with the pinned source, installed Python and web dependencies and local Git objects for both original publications. The collector builds the frontend with its API at 127.0.0.1:8818. Each cold arm starts from empty local queue, cache and browser storage. The warm pass preserves the state of that arm. The experiment made no provider calls and uses published expected points only.
