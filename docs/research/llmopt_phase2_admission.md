# LLMOPT shared admission budget

The local replay of the immutable Phase 1 member-week identities admitted at most four
server jobs per run. Reconstructed services and repeated terminal requests created no
additional jobs. This is an admission/storage measurement with synthetic completions,
not a football-quality or solver-latency measurement.

| Check | Recorded result |
| --- | --- |
| Frozen member-weeks | 20, from `llmopt_phase1/inputs.json` |
| Windows and runs | 1 and 3 weeks; 40 runs |
| Admitted jobs | 160 total; maximum 4 per run |
| Reconstructed-service repeats | 240; 0 additional jobs |
| Fifth requests | All 40 refused with `RUN_BUDGET_EXHAUSTED` |
| Capacity reserved per run | 84 at one week; 488 at three weeks |
| Solver invocations / network requests | 0 / 0 |

The [record](llmopt_phase2_admission.json) retains every member, window, reservation,
refusal and producing commit. Reproduce with
`python -m docs.research.llmopt_phase2.measure_admission`, separately from tests.
The [runner notes](llmopt_phase2/README.md) describe the synthetic boundary.

[ADR 0018](../architecture/decisions/0018-llmopt-run-budget.md) derives the capacities
from the unchanged [Phase 1 record](llmopt_phase1_baseline.md): four server jobs, twelve
internal calls at one week, sixteen at three weeks. Each job reserves its existing main
solver limit plus hold/certificate work and the native maximum wall reservation. Actual
deterministic work is retained separately. Engine stop granularity is not hidden or given
a larger accounting tolerance; an exhausted allocation starts no further nested solve.

API tests additionally cover simultaneous admissions, restart, terminal retry, base-first
admission, cache hits, shared queued cancellation and a running result fence. Browser
tests cover the same run identity after reload, four completed requests after reload and
editing a waiting run without creating a follow-up. The running solver is not killed.

The exact served GW8/GW9 football bundles needed by the separate five-free-transfer
investigation remain unavailable locally. This phase changes no frozen Phase 1 receipt
and makes no claim that the earlier expected-window accounting defect was reproduced.
