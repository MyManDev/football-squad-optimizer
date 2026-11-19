# LLMOPT Phase 6: full-pool package comparison

Producer: `cdafbac3d507f28c5b735103d20e863cbf9738f6`. Twenty unchanged frozen Phase 1 member-weeks.

Decision: [ADR 0022](../architecture/decisions/0022-llmopt-transfer-packages.md).

The retained prefix is computed once and charged in full to each comparison arm. Every arm has the same 60 CP-unit window, 122 admitted units, 1,800-second wall ceiling and a cap of 1,153 exact lineup evaluations. No tests run alongside this local replay. These are algorithm comparisons, not independent cold-request latency measurements. No realized scores or live service are used.

Frozen metrics match exactly in 18/18 computed cases. Network attempts: 0.

| Arm | Computed | Errors | Accepted packages | Highest charged units | Raw XI gain | Expected net gain | Selection utility gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| disabled | 18 | 2 | 0 | 122.000084823 | 0.000000000 | 0.000000000 | 0.000000000 |
| packages | 18 | 2 | 0 | 122.000084823 | 0.000000000 | 0.000000000 | 0.000000000 |
| opened_gate | 18 | 2 | 0 | 122.000084823 | 0.000000000 | 0.000000000 | 0.000000000 |

Gains aggregate only computed cases. Error cases retain null gains and remain in the twenty-member denominator. The complete all-twenty condition is `False`.

The two five-free-transfer member-weeks fail inside the unchanged retained algorithm. Both enabled arms retain those errors rather than replacing them with a zero gain. The actually served football input bundles needed to reproduce and fix them were unavailable in the separate preliminary probe.

Inherited capacity overruns in the disabled algorithm: gw8-5349883 = 122.000084823223. No new package work starts after that allocation is exhausted. This existing stopping-granularity issue remains visible; the cap and accounting tolerance were not increased.

| Member-week | Arm | Raw XI difference | Expected net difference | Selection utility difference | Outcome |
| --- | --- | ---: | ---: | ---: | --- |
| gw8-313686 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw8-313686 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw8-2199732 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw8-2199732 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw8-2281624 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw8-2281624 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw8-3832237 | packages | null | null | null | ERROR |
| gw8-3832237 | opened_gate | null | null | null | ERROR |
| gw8-4287206 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw8-4287206 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw8-5081114 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw8-5081114 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw8-5349883 | packages | 0.000000000 | 0.000000000 | 0.000000000 | no_remaining_budget |
| gw8-5349883 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | no_remaining_budget |
| gw8-5662073 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw8-5662073 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw8-6654210 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw8-6654210 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw8-6879786 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw8-6879786 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw9-313686 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw9-313686 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw9-2199732 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw9-2199732 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw9-2281624 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw9-2281624 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw9-3832237 | packages | null | null | null | ERROR |
| gw9-3832237 | opened_gate | null | null | null | ERROR |
| gw9-4287206 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw9-4287206 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw9-5081114 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw9-5081114 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw9-5349883 | packages | 0.000000000 | 0.000000000 | 0.000000000 | no_remaining_budget |
| gw9-5349883 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | no_remaining_budget |
| gw9-5662073 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw9-5662073 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw9-6654210 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw9-6654210 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |
| gw9-6879786 | packages | 0.000000000 | 0.000000000 | 0.000000000 | original_routes_incomplete |
| gw9-6879786 | opened_gate | 0.000000000 | 0.000000000 | 0.000000000 | retained_incumbent |

## Reproduction

```powershell
$env:PYTHONPATH='src'
python -m docs.research.llmopt_phase6.measure
python -m docs.research.llmopt_phase6.report
```

The JSON includes proposed component metrics even when the conservative acceptance guard retains the incumbent. Review those tradeoffs before activating either disabled control.
