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

## Actual solver controls

The [readout](../llmopt_phase2_solver_budget.md) and
[record](../llmopt_phase2_solver_budget.json) retain all forty results and work receipts.

`python -m docs.research.llmopt_phase2.measure_solver_budget` complements the admission
replay with all twenty frozen member-weeks at both windows. It obtains real durable
21/122-unit allocations, runs the production planner on the exact Phase 1 controls,
records every internal solve and work receipt, and compares status, objective and
decision fingerprints with the unchanged baseline. Infeasibilities are separate from
numeric matches. Native execution, if used, reserves its allowance before starting.
The queue setup is local measurement bookkeeping, not a served football-bundle or
end-to-end public-API claim. Run it serially and separately from tests.

## Named-chip worker parity

`python -m docs.research.llmopt_phase2.measure_named_chip` runs the local API and worker for
the eight Wildcard and Free Hit member-weeks in the frozen Phase 1 baseline. Each one- and
three-week request runs twice from an empty queue and cache. One request carries a durable run
reference and the other omits it. The captured member, prices, expected points, fixtures,
configuration, chip and preferences are shared by both workers. The capture adapter reconstructs
an equivalent purchase basis for the published initial sale proceeds at static prices.

The runner writes [the raw pairs](../llmopt_phase2_named_chip.json) and
[the comparison](../llmopt_phase2_named_chip.md). Pass `--output PATH` to retain a separate
implementation's replay. To regenerate the Markdown from an existing record, run
`python -m docs.research.llmopt_phase2.named_chip_readout PATH`. Run the solver replay
serially and separately from tests.
