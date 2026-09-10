# Solver boundaries

The live squad path (`live.report` → `optimization.optimize_squad`) and live transfer path
(`live.transfers` → `planning.optimize_transfer_plan`) share the same squad/lineup invariants.
Those helpers live in `optimization.decisions`; planning imports that module directly.

| Shared helper | Responsibility |
| --- | --- |
| `add_decision_constraints` | Squad/XI/captain counts and nesting, position quotas, team limits and optional static affordability. |
| `selected_indices` | Read selected variables in their existing model order. |
| `verify_solution` | Check the same solved squad invariants, with the same optional static budget. |

The helpers previously lived inside `optimization.optimizer` and were already shared by
these consumers. Extraction makes that ownership explicit; it introduces no second
implementation. The original private imports `_add_decision_constraints`, `_selected_indices`
and `_verify_solution` remain re-exports for one release, including the scenario solvers and
tests that still consume them. Removal is separate work under the dependency rules.

Static optimization enforces the squad's total price against its budget. Transfer planning
passes `enforce_budget=False` and checks affordability through its existing bank, buy/sell
prices, free transfers and chip transitions. Disabling static affordability does not disable
the other squad checks.

Model variable creation, constraint insertion order, objective coefficients, deterministic
seed/settings, time budgets, tie-breaks, fingerprints and result arithmetic remain at their
existing call sites. The shared helper performs no solve and makes no strategy decision.

Output assembly is intentionally outside this boundary. Baseline optimization orders its
bench goalkeeper first and outfield players by descending expected points, then player ID;
planning currently preserves canonical player-index order. Baseline projected scores use
Decimal accumulation; planning uses its existing pandas sum and chip adjustments. These
are different behaviors and were not unified as part of this extraction.

Validation covers helper identity, budget ownership, invariant refusal and selection order,
plus the existing baseline, planning, live and scenario consumer tests. The extraction also
compares the moved executable AST, binary CP-SAT models and synthetic solved outputs before
and after the move. No historical evidence or published recommendation is regenerated.
