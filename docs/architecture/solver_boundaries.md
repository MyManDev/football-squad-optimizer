# Solver boundaries

The live squad path (`live.report` → `optimization.optimize_squad`) and live transfer path
(`live.transfers` → `planning.optimize_transfer_plan`) share the same squad/lineup invariants.
Those helpers live in `optimization.decisions`; planning imports that module directly.

| Shared helper | Responsibility |
| --- | --- |
| `add_decision_constraints` | Squad/XI/captain counts and nesting, position quotas, team limits and optional static affordability. |
| `selected_indices` | Read selected variables in their existing model order. |
| `verify_solution` | Check the same solved squad invariants, with the same optional static budget. |
| `add_tiebreak_objective` | Fix the proven primary value and minimize the canonical rank-weighted tie-break among squads of equal objective value. |

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
seed/settings, time budgets, tie-breaks, fingerprints and result arithmetic remained at their
existing call sites when the three helpers were extracted. The shared helpers perform no solve
and make no strategy decision.

The solver itself has one public port since [ADR 0011](decisions/0011-storage-ports-and-platform-split.md)
(decision 5): `optimization.cpsat` holds `configure_solver`, `solve`, `raw_status_name`,
`map_solver_status`, `deterministic_time_used`, `remaining_deterministic_time` and the three
budget constants, bodies moved unchanged from `optimization.optimizer`; the tie-break objective
joined `optimization.decisions` as `add_tiebreak_objective`, and the empty result
`optimization.models` as `empty_result`. Each consumer (`optimization.optimizer`,
`planning.optimizer`, `scenarios.optimization`, `scenarios.rank`) binds the public names to the
module-level private names it had, so the tests that patch `_solve` or
`_deterministic_time_used` on a consumer keep their seams; `tests/unit/test_cpsat_driver.py`
holds the bindings, and `tests/architecture/test_private_imports.py` refuses a new private
import across packages. The solve sequences (probe, primary, tie-break) stay with their callers.

Output assembly is intentionally outside this boundary. Baseline optimization orders its
bench goalkeeper first and outfield players by descending expected points, then player ID;
planning currently preserves canonical player-index order. Baseline projected scores use
Decimal accumulation; planning uses its existing pandas sum and chip adjustments. These
are different behaviors and were not unified as part of this extraction.

Validation covers helper identity, budget ownership, invariant refusal and selection order,
plus the existing baseline, planning, live and scenario consumer tests. The extraction also
compares the moved executable AST, binary CP-SAT models and synthetic solved outputs before
and after the move. No historical evidence or published recommendation is regenerated.
