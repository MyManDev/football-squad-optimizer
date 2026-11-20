# LLMOPT priorities and one preference job

The solver certifies the required plan's decisions, recomputes its integer objective
and applies the total concession floor. It maximizes up to three priority counts in
order. The first unproved count stops the count search. When a count has been proved,
the solver keeps the strongest points witness for the proved counts and can spend
the remaining allocation on the points tie break. With no proved count it returns
the certified main plan.

`python -m pytest tests/unit/test_priority_preferences.py -q` exercises the solver. The independent
oracle enumerates all 16 final transfer packages and both legal lineups in each tiny
football case, rather than calling the production optimizer for its expected answer.
Other cases cover exact boundaries, conflicting soft/hard rules, all six writing-order
permutations, a forged numeric reference claim, three weeks and interrupted layers.

## Public execution

Public advice admission, immutable requests, the durable run allocation, worker,
provider interpretation and page share the execution in ADR 0019. The main job
reserves 21/122 units; one preference job reserves 63/366 within the original
84/488-unit capacity. Old individual prices and their combination run sequentially
inside that job. A total allowance skips individual prices and executes count layers.

`test_llmopt_preference_bundle.py` exercises the actual API and real worker at both
windows, fixed Free Hit, immutable main binding, receipts, reconstructed-service
cache reads, legacy prices, incomplete graphs and repair diagnoses. The page pins its
transport before the main request. Its compiler tests compare price acceptance with
the legacy compiler, including shared prices with different ceilings.

`e2e/llmopt-priorities.spec.ts` covers both languages and windows, legacy and
total modes, partial results, failed searches, pending and completed reload,
two POSTs and phone overflow. The API and worker tests check actual server job counts.

`python -m docs.research.llmopt_phase3.measure` replays the twenty frozen member-weeks
through local API admission and the real worker, consuming frozen point tables.
Scoring and forecasting are guarded against invocation. Scenario chip rights and
timestamps are replay controls, without claims about a live member's entitlements or
deadline. The priority arm reuses a completed main answer when available, explicitly
reported. Run separately from tests and CI.

The replay with the revised priority search produced 80 API and worker records. Each run opened at most
two jobs, every receipt stayed within allocation, and 192 repeats after service
reconstruction opened zero extra jobs. At three weeks, 10/20 member-weeks completed
three layers, or 10/16 with a feasible main, up from 9/16 previously. Four eligible
runs completed one layer and two completed two. Ten of their 48 submitted rules were
unsearched. The four contradictory cases opened no preference job. All 16 eligible
one-week programs completed three layers. [Complete replay](llmopt_phase3_jobs.md)

Certificates, count searches and the points tie break share up to 63 units at one
week or 366 at three weeks. The one-week preference jobs used 22.366716274 CP units
and zero native units out of 1,008 available. The three-week preference jobs used
2,644.991671485 CP units plus 16 reserved native units out of 5,856 available.
The record includes per-job charges and completed layers. [Job receipts](llmopt_phase3_jobs.json)

Frozen Phase 1 artifacts are unchanged. Counterfactual scenarios keep their existing
transport; a new total allowance on that path is refused before starting work.
