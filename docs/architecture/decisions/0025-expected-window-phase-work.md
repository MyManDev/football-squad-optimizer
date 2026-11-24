# ADR 0025: Admit expected-window search against measured remaining work

- **Status:** Proposed.
- **Date:** 2026-11-20.
- **Decider:** The owner.
- **Related:** [Phase 1 full-pool comparison](../../research/llmopt_phase1_baseline.md), [served-route preflight](../../research/llmopt_window_budget_probe.md).

## Context

The frozen three-week experiment gives a 60-unit window 24 units for the
legacy proposal and 36 for the zero-bonus proposal. Inside each proposal a
segmented construction receives 10% and the guarded full-window solve
receives 90%, including protection. CP-SAT checks a deterministic limit at
search boundaries. Its reported work can exceed the requested limit.
Issuing the next nominal allowance after an earlier overspend can therefore
commit more work than the phase has left.

The Phase 1 record for entry 3832237 reports 24.0587449622 units in GW8 and
24.2239097074 in GW9 against the 24-unit phase. Both used the frozen baseline
forecast. The separate ready-football preflight for GW6 selected the
observed-information route and completed. The two GW8/GW9 records describe
the expected-window route under the archived experimental inputs.

## Options

1. Increase the accounting tolerance or charge the requested limit when the
   solver reports more. Either would hide work already consumed.
2. Apply a fixed safety margin to every search, split the phase differently,
   or lower the five-transfer entitlement. Each would change work or decisions
   for cases with sufficient remaining capacity.
3. Keep the nominal allocations and deduct measured work before admitting a
   dependent search. If a bounded last call crosses the phase boundary,
   preserve a complete, already verified feasible plan and disclose the stop.

## Decision

Use option 3 for the expected-window path. A dependent search can receive
at most its original nominal allowance and the remaining applicable work.
The hold probe and incumbent certification remain part of the account. A
depleted phase cannot start another solve. A stopped window can retain only
a complete plan checked against the original full-window rules. Its status
is feasible, with no claim of an unrestricted optimum. The report carries
the actual work, including any excess. An overrun cannot fund a later phase
or optional refinement. Missing solutions, invalid work receipts and wall
clock failures retain their existing refusal behavior.

The same retention check applies to the original proposals and optional
transfer packages. It requires a complete plan for the current horizon and an
unrounded work receipt within the applicable aggregate ceiling. Original
proposals certify their protected witness before retention. Optional
packages retain the already completed baseline. Neither route may start
another solve after it reports a budget stop, even with the package gate
open. A shared job retains its full native charge and actual solver work.

The 60-unit ceiling, 40/60 and 10/90 allocations, 0.01 accounting tolerance,
lineup evaluation limits, forecast, hard rules and selection objective stay
as configured. Compare both five-transfer cases with the frozen run, and
check the completed plans, points and decisions of the other eighteen
member-weeks at the same settings.
