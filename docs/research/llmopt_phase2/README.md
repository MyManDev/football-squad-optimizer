# Durable run admission replay

The [readout](../llmopt_phase2_admission.md) and [record](../llmopt_phase2_admission.json)
retain the admission counts, scope and producing commit.

`python -m docs.research.llmopt_phase2.measure_admission` replays the actual local submission,
queue and run-ledger adapters for the 20 immutable Phase 1 member-weeks, at both windows.
Each replay completes a synthetic base, admits three distinct preference requests, repeats
them through reconstructed services, and attempts a fifth job. It records admission counts
and reserved capacity. It does not execute a solver or measure football quality/latency.

Run separately from tests. The input loader checks the committed Phase 1 hashes; this runner
never writes the frozen inputs or Phase 1 records. The record retains the producing commit
and the normalized runner digest. ADR 0018 derives the 84/488-unit capacities from the
Phase 1 production-path ceilings rather than from synthetic completion timing.
