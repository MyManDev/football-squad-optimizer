# One-week device parity and alternatives

Run from the repository root, with its Python environment and `web/node_modules` installed:

```
node docs/research/llmopt_phase4/bundle.mjs
python -m docs.research.llmopt_phase4.measure
```

Run measurement separately from tests. The script reads the unchanged Phase 1 manifest
and both frozen published input tables. On each of twenty member-weeks it keeps the
first held player, then compares ordinary selection utility and net points separately.
The local server function uses the active preference path's 20 deterministic units,
1,800-second ceiling, linearization level 2 and hold protection. No queue or live endpoint
is involved. This does not replace the missing served football bundles from the prework.

The [record](../llmopt_phase4_parity.json) has **40/40 equal objectives**, **40/40 equal
transfer decisions**, and all searches proved their primary result. It compares integer
model values with integer model values and independently reconstructs the device's
published value before comparing published values. The first attempted comparison mixed
the unrounded server publication with the rounded device model; that was corrected
without widening the 1e-8 equality check. Both values remain in the final record.

The forty server-function calls took 56.46 seconds in total, maximum 2.46; the forty
device problems took 30.70 seconds, maximum 3.73. These are local descriptive timings,
with different internal solve orchestration, not a live latency or football-quality claim.
The measurement itself opens zero server jobs.

## Device scope

The verified one-week path supports keep/include/avoid, no hits, saving chips, holding
transfers, club counts, first-week purchases, hit ceilings, persistent bank floors and
frozen first-week decisions. Future-week rules, scenarios, a named football model,
manager news and preference combinations with chips or Top100 remain on the server.
The new Phase 3 priority transport is incomplete and is not claimed as migrated.

For a one-week hard-rule run with device inputs, the page uses the existing net-points
objective for its main plan and the local menu. It shows at most three Pareto decisions
inside 6.3 points of the computed net-points main. A resource lexicographic solve finds
each decision in the remaining non-dominated region; integer disjunctions retain equal
resource vectors and exclude strictly dominated ones. Exclusions remove the complete
squad, so captain/lineup changes do not repeat a transfer decision. The independent tiny
oracle enumerates all sixteen transfer packages and legal lineups.

Real-worker E2E covers English/Turkish at 1280 and 375 pixels, three distinct decisions,
hard-player preservation, reload identity, zero server POST jobs and no horizontal overflow.

## Original-control scope audit

The [audit result](../llmopt_phase4_scope_audit.md) reports all sixty comparisons,
including the original incumbent mismatch. The historical 40/40 result above is not
substituted for that finding.

The historical 40/40 record adds a keep-first-held-player constraint to every case.
It cannot establish parity for the original Phase 1 controls or an unrestricted run.
Keep that record unchanged and audit those scopes separately:

```
python -m docs.research.llmopt_phase4.audit
```

Read the scenario identities directly from the frozen Phase 1 result. For all twenty
member-weeks, replay its exact control with its original settings and default
linearization, then the same control with the served preference path's linearization
2 and 20-unit allowance. Also solve the served profile with no added player rule,
retaining the zero bank for the tight-bank members. The original controls include
forced Wildcard/Free Hit, four contradictions and the unproved zero-bank case.
Never add the historical keep rule, change J to a newly found better value, increase
the work allowance or warm-start the reference to make the comparison pass.

The device probe calls the production `solvePlan`, including publication and the
hold-score calculation, under one cumulative 120-second ceiling for the complete
answer. Infeasibility agreement is counted separately from numeric objective equality;
two missing numbers are never counted as an equal objective. If a transfer decision
differs, retain the actual squads and both computed scores to check a true tie.
Measurement is sequential and runs without tests or a live service. These remain the
frozen published-coefficient models, not the unavailable served football bundles.
