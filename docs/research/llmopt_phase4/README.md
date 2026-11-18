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
