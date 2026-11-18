# LLMOPT vNext, Phase 1 baseline

Scope: measurement only, from `origin/develop` at `0078a43c6207026cfb506d94806101bdf7c6dc50`.
No production source, preference contract, result contract, deployment or solver policy changes.
The following phases require their own review. Phase 6 additionally requires measured benefit
and explicit owner approval.

## Current capabilities, verified in source

| Capability or rule | Current behaviour | Work and location |
| --- | --- | --- |
| Chat and validation | `/prompt` prepares the call; `/check` checks the member provider's reply. The key stays in tab memory. Both routes are write-free and call no model. | 0 advice jobs. [Backend routes](../../src/squadopt/api/llmopt.py), [intent and typed provider schema](../../src/squadopt/platform/llmopt_intent.py), [ADR 0017](../architecture/decisions/0017-llmopt-own-key.md). |
| Hard rules | Keep/include/avoid player, dated buy, hold transfers, no hits, save chips, Wildcard, exact club count in squad/incoming transfers, total hit limit; up to 16 hard plus soft rules. Global and relative weeks 1 to 3 are supported. | Applied to every requested branch by [intent.ts](../../web/src/features/league/llmopt/intent.ts) and [preferences.py](../../src/squadopt/contracts/preferences.py). No explicit draft Free Hit rule. |
| Soft rules | Same rule kinds, with optional individual `max_cost_tenths`. Written order determines which rules get a pricing slot and which fit the combined plan. No explicit priority field or common concession budget. | [prepareRun](../../web/src/features/league/llmopt/planRun.ts) reserves at most 2 distinct individual pricing requests. Duplicate requests share a slot; other rules may be skipped. |
| Base and pricing | Hard-only base; after the base, individually price preferred rules in reserved slots. Pricing maximises unweighted expected net points, with no terminal resource value. Individual costs are measured against the base and checked against individual ceilings. | 1 base plus up to 2 priced backend jobs. [Slots](../../web/src/features/league/llmopt/planSlots.ts), [prices and displayed results](../../web/src/features/league/llmopt/planResults.ts). |
| Combined preferences | Once prices return, combine accepted rules and unbounded unslotted rules, in written order. Bounded unslotted rules cannot be accepted without their own verified price. | At most 1 more backend job, hence 4 named slots total. [Combined plan](../../web/src/features/league/llmopt/combinedPlan.ts). This is slot accounting, not a shared work budget or a proof about reloads and repeated confirmations. |
| Comparisons and automatic alternatives | Explicit constrained/unconstrained comparisons; without soft pricing, free slots may roll transfers or keep more bank. Repeated opening decisions are hidden. Explicit branches can start alongside the base. | Base plus at most 2 alternative slots; optional combined slot remains the fourth. [Page effects](../../web/src/features/league/llmopt/LLMOptPage.tsx). No transfer-decision exclusion search. |
| One week, current LLMOPT | The page uses the HTTP/static advice client and always prepares preference objects. It does not mount `useDevicePlan`. The device selector rejects any request with preferences. | Current LLMOPT runs on the backend for 1 week as well. This differs from the requested future device-only rule and is recorded, not changed in Phase 1. [Device selection](../../web/src/features/league/device/selection.ts). |
| One week, ordinary advice | Plain plans, held chips including Free Hit, rival plans and supported Top 100 weights can run in browser HiGHS. Each proved plan can contain a primary solve, three tie-break tiers and multiple hold/move attribution solves. | 0 backend jobs on eligible device requests; solver calls are not jobs. [Device requests](../../web/src/features/league/device/requests.ts), [week solver](../../web/src/features/league/device/solve/week.ts). |
| Three weeks, priced LLMOPT | `net_points_priority` bypasses guarded/expected-lineup search and uses game transfer limits. One week is uncapped; three-week priced requests are also uncapped by the member's narrower one-transfer policy. | Native HiGHS primary in the worker, checked by CP-SAT, with CP-SAT fallback, hold probes and tie breaks inside the same backend job. [Dispatch](../../src/squadopt/live/transfers.py), [native boundary](../../src/squadopt/planning/native_highs.py). Production 3-week budget: 60 deterministic CP units, 1,800-second wall safety ceiling per configured path. |
| Expected-window refinement | Separate eligible football forecast path: 40/60 original proposals, lineup rescoring, optional single initial swap only when both originals complete. It uses remaining CP work and at most 128 additional lineup evaluations per week plus one template score. | Several internal solves inside 1 backend job. It is not the priced LLMOPT objective. [expected_window](../../src/squadopt/planning/expected_window.py), [single swap](../../src/squadopt/planning/expected_swap.py). |
| Existing candidate generator | Top-K complete squad/starting-XI/captain decisions with exclusions; stops on an unproved solve. Its identity includes lineup and captain. | [candidates.py](../../src/squadopt/optimization/candidates.py); it is not a transfer-identity alternative generator in LLMOPT. |
| Plan revisions and scenarios | Keep previously solved weeks; bank floor; hypothetical absence/price increase and original-plan comparison. Saved confirmations restore slot requests. | Existing slots, not a new conversational plan-ID contract. [Page](../../web/src/features/league/llmopt/LLMOptPage.tsx). E2E helper [routeChat/holdModel](../../web/e2e/llmoptChat.ts) requires `holdModel` after every page load. |

## Frozen population and protocol

[Input manifest](llmopt_phase1/inputs.json) pins 20 distinct member-weeks: the ten lowest
numeric member IDs with complete device blocks at GW8 and GW9. Publication commits and capture
identities, member sell prices, bank, free transfers and fixture counts are frozen in
[GW8](llmopt_phase1/gw8.json) and [GW9](llmopt_phase1/gw9.json). Nothing is fetched during a run.
The input selection uses no realised scores. Normal, forced Wildcard, forced Free Hit, zero-bank
and conflicting hold/include scenarios rotate deterministically over each ten members.
Forced chips are solver stress controls, not a claim that the draft supports a Free Hit rule
or that the historical member chose that chip. They call the full-horizon planner directly,
bypassing the production named-chip dispatcher and its allocation policy.

Both 1- and 3-week controls use published points, the planner's net-points preference and
current game transfer limits. Later weeks repeat points scaled by captured fixture counts,
as the existing publication replay runner does. Controls include build and result-reading
time. The 1-week call supplies no deterministic cap and a 10-second requested wall limit.
The planner applies its default **20 deterministic units** and **300-second effective wall
floor**. The 3-week call supplies **60 units** and **1,800 seconds**. Compact records retain
requested/effective limits, actual work, budget exhaustion and clock-stop flags; per-call
receipts retain each solve's parameters. Times are sequential local elapsed seconds,
not production service or queue latency.
Conflicting controls deliberately reach the solver. The current web preparation can reject
hold plus an unheld include before admission; an `INFEASIBLE` stress solve is not a claim
that the page opens a backend job for that draft.
Only the first member of each capture additionally replays a full three-soft-rule run at
both horizons: base, two individually priced keep rules and the combined plan that also tries
the unslotted no-hit rule. All preferences in that workload are unbounded. Its generated
requests come from the actual web `prepareRun`, `combinedCandidates` and `prepareCombined`.
Admissions use an empty isolated `FileJobQueue`; this measures cold local queue job creation,
not the API's complete cache/idempotency or cancellation behaviour. Local model execution
is serial and its total is the sum of these jobs, excluding HTTP, polling and orchestration.

Every CP-SAT call, including a native witness certificate, hold probe and tie break, and every
native HiGHS child call is counted separately. Successful calls report their actual search
thread count. Unknown counts, including a failed native attempt before its receipt, are
explicitly recorded rather than assumed to be one. A job is a
queue admission, never a synonym for a solver invocation. A primary proof does not prove
arbitrary later rescoring. A missing global bound/gap is `null`, never an invented zero.
Per-call raw bounds refer only to that call's model and units, especially on tie breaks.

The independent expected-window experiment uses the matching capture's saved forecast points
and appearance probabilities on the original captured member state, without the rotated
control scenario. Later weeks repeat that captured appearance probability. Those saved
handoffs identify the deterministic baseline
forecast, not the deployed football candidate. Players with missing appearance probabilities
are excluded from both arms, with IDs recorded; every held player remains. Therefore this is
a bounded algorithm diagnostic on captured inputs, not an operational football-quality claim.
The baseline calls the unchanged `optimize_expected_window`. The experimental arm replaces
only its optional proposal inside the research process. Original 40/60 proposals, original
transaction state, configured 60 CP units, wall safety ceiling, one optional fixed-first-squad
solve and 1,153 lineup-evaluation ceiling are shared. HiGHS has a wall ceiling rather than a
CP deterministic budget; its time is recorded separately. Equal configured ceilings do not
claim equal realised CPU work. Clock-truncated/incomplete proposals must be read as such.
The unchanged work-accounting check permits a 0.01-unit tolerance. Slight overruns within
that tolerance stay visible in recorded actual work; they are not rounded down to the cap.
The experiment's configured cap and the wrapper's `actual_units` describe the whole
comparison arm. An arm's `solver_limits` describe the selected internal proposal; its
fractional allocation is not the whole wrapper's budget.

The optional experimental proposal considers singles plus pairs from a fixed shortlist of
24 highest point proxies and 8 largest cash releases. All singles are checked first; disjoint
pairs are ranked by descending combined proxy with player-ID ties **before** the existing
`15 * outsider_count` check cap is applied. Generated, checked and truncated package counts
are recorded. This remains a bounded prefix, not an exhaustive pair enumeration. It tests
whole-package bank, club, required players, hit and transfer limits, then validates one
selected first squad with the
full horizon planner. Cash-releasing moves can enter even if individually unattractive.
The member policy is preserved: the second move requires two banked free transfers. This
experiment does not relax the one-transfer policy to admit paid two-move packages.
It is a proxy shortlist, not exhaustive package search. Actual candidate checks and lineup
work are disclosed. A failed package can lose an optional opportunity; neither arm is silently
given the other arm's extra solve. Three paired metrics are recorded separately:

- `raw_xi_net_points`: the sum of `projected_score - transfer_hit_points`, a raw XI and
  captain projection which omits appearance, autosubs and vice-captain effects.
- `expected_lineup_net_points`: the sum of the scorer's `lineup_expectation.expected_net_points`,
  including those effects and actual game hit charges. This is the expected-point comparison.
- `selection_utility`: the unchanged wrapper's discounted expected-week utility plus terminal
  resource values. It can differ from scored net points through the points basis, discount,
  resource values and the policy's 8-point transfer cost versus the game's actual 4-point hit.

These are forecasts, never realised points. No rescored result gets a global
optimality claim from a surrogate CP proof.

## Reproduction

Use the repository's Python development environment and pinned web dependencies. Set
`PYTHONPATH=src` so an editable install for another checkout cannot select the wrong code.
For a fresh environment, install `.[api,dev]` with `constraints.txt` as described in the
contribution guide and run `npm --prefix web ci` before bundling the probe.

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
node docs/research/llmopt_phase1/bundle.mjs
python -m docs.research.llmopt_phase1.benchmark
```

`bundle.mjs` optionally accepts the path of an existing `web/node_modules`; it writes only
the schedule bundle under this checkout's ignored `.codex-tmp`. The frozen inputs are enough
to run the measurement. `freeze.py --handoffs PATH` documents extraction of the original
inputs and requires the saved private handoffs and publication history only when rebuilding
the input snapshots. The file and normalized content hashes are preserved.
`--limit 1 --output .codex-tmp/phase1-pilot` is a pilot, not the full population. On Windows,
the queue's atomic hardlink writes require a process that is allowed to create hardlinks.

The [result record](llmopt_phase1_baseline.json) carries code commit, runner digests and input
digest. Detailed receipts in ignored `artifacts/llmopt_phase1_v2/` carry plans, resource transitions,
raw solver status/bounds and per-call counts. They are regenerated evidence, not the committed
record (ADR 0003). Alternate `--output` paths write their own `summary.json` and cannot replace
the committed summary. `--resume` accepts only identical committed code and input digests;
partial cases are never aggregated.

The revision-1 record at commit `4ffabf7abc290534ee1bd40030aa66f5519061b1` is
superseded. Independent review found a biased pair enumeration prefix and a misleading point
field name. Revision 2 ranks pairs before truncation, separates the three point bases, records
effective budgets and failure accounting at every imported alias, and avoids solving duplicate
queue admissions. All 20 cases in both experiments are rerun from the same frozen inputs;
revision-1 cases are not reused. `--reuse-completed` now requires identical protocol, input
and all research source hashes, plus unchanged product/replay-builder code. Known accounting
and wall-limit refusals have status `ERROR` and null gain; other exceptions stop the run.
Pilot runs require a separate output path and cannot overwrite the primary compact record or
its raw evidence. Wall times naturally vary between repetitions.

After the first three full-pool pilot cases all skipped optional refinement because their
sequential seeds did not complete, a separate diagnostic was added before its own measurement.
[neighborhood.py](llmopt_phase1/neighborhood.py) fixes a smaller pool: all held players plus
the top four forecast players and cheapest two players of each position, ID ties. It retains
the same captured points/probabilities, 60-unit budget, original wrapper and two experimental
arms. Its [separate record](llmopt_phase1_neighborhood.json) never replaces a full-pool result.
This is a development diagnostic of proposal coverage, not a held-out result or a tuned
operational candidate pool. Reproduce it after the full-pool run, without overlapping CPU work:

```powershell
python -m docs.research.llmopt_phase1.neighborhood
```

## Questions reserved for the later ADR

1. How do the required “two solutions” relate to the required up to three sequential priority
   layers and the final point tie break? Which are logical stages, internal solver calls and
   backend jobs? Phase 1 makes no decision that resolves that wording.
2. When the first solution J is unproved, is J an incumbent or a proven optimum? Does the
   concession guarantee refer to that incumbent, an upper bound or a later proven value?
   No silent substitution or claimed optimality is permitted.
3. How do an individual ceiling and the shared ceiling compose? Which guarantees survive
   rounded objective coefficients, equal-priority ties, infeasible packages and budget expiry?
4. How will the requested one-week device route support preferences and the current LLMOPT
   orchestration? Current device advice support does not establish that capability.
5. Which complete run, including reloads, joins, explicit branches and cancellations, owns
   the four-job and total-work budget? Mounted slots alone do not define that contract.
6. Would a future package search preserve the member's two-free-transfer exception or admit
   paid two-move packages too? This measurement keeps the existing policy in both arms.
7. How should Phase 6 qualification relate raw XI points, expected-lineup net points and
   selection utility when their directions differ? These metrics must not be silently
   substituted for one another, or for a full-pool operational benefit.

## Results and phase handoff

Revision 2 reruns the complete **20 member-weeks and 40 window controls** with the same
frozen inputs. There are four of each control scenario. Recorded successful solver calls
report one search thread. These are descriptive local times with one observation per
condition, not production latency or forecast quality.

| Window | Optimal | Feasible, unproved | Infeasible | Seconds, min / median / max |
| --- | ---: | ---: | ---: | --- |
| 1 week(s) | 15 | 1 | 4 | 0.082 / 3.700 / 30.315 |
| 3 week(s) | 16 | 0 | 4 | 0.805 / 17.158 / 40.334 |

All 31 optimal controls have a zero model gap. The eight infeasible controls have no
incumbent or gap. `gw9-3832237`, the one-week zero-bank control, is **FEASIBLE**, not proved:
incumbent **52.310**, best bound **58.561**, gap **6.251 points**. It uses **20.0005814292**
deterministic units against the planner's 20-unit default and records budget exhaustion;
`wall_clock_stopped` is false. No control records a wall-clock stop. This is an example for
the later unproved-J decision, not an optimality claim. Optimal primary status and budget
exhaustion can coexist when later tie breaking consumes the remaining budget.

### Individual pricing workload

| Member-week | Window | Local backend jobs | CP-SAT calls | Native calls | Total solver calls | Computation seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gw8-313686 | 1 | 4 | 12 | 0 | 12 | 7.647 |
| gw8-313686 | 3 | 4 | 12 | 4 | 16 | 45.255 |
| gw9-313686 | 1 | 4 | 12 | 0 | 12 | 8.709 |
| gw9-313686 | 3 | 4 | 12 | 4 | 16 | 100.327 |

Across these four cold local runs: **16 admitted jobs, 48 CP-SAT calls, 8 native calls,
56 solver invocations**, and **161.937 seconds** of computation. All 16 requests are distinct;
none joins an existing local request in this workload. The unbounded third no-hit preference
enters the combined request without an individual pricing slot. A dedicated regression checks
that a repeated admission reuses the completed local result without executing another solve.
This does not prove whole-run, reload, cancellation or API-cache guarantees.

### Full-pool comparison

Both arms return a plan in **18 of 20 cases**. Their raw XI net points, expected-lineup net
points and selection utilities are identical in all 18. In **16 cases**, the original
construction routes do not meet the wrapper's completion gate, so neither optional proposal
runs. In **2 cases**, an optional proposal is evaluated and the retained original still wins.
One experimental proposal contains two actual transfers. Zero paired gain here does not
establish that all two-move packages have zero value.

The other two cases fail the unchanged wrapper's phase-work check in both arms:
`gw8-3832237` records **24.0587449622 / 24.0** units and `gw9-3832237` records
**24.2239097074 / 24.0**. These are phase-cap refusals, not evidence that the full 60-unit
budget was spent. Their gains are **null**, not zero. No production tolerance was changed.

### Restricted-pool diagnostic

The separate declared pools contain **33 to 36 players**. Both arms reach optional refinement
in all 20 cases under the same 60-unit and 1,153-lineup-evaluation ceilings. Every arm reaches
that lineup ceiling; optional lineup searches report exhaustion in all three weeks. The
proposal prefix remains truncated, with checked/generated/truncated counts in each record.
It is not exhaustive package or lineup search.

There are **17 equal results and 3 gains in expected-lineup net points**, totaling
**1.1292453273 points** across 20 paired cases. All three changed plans use two free transfers.

| Member-week | Single expected net | Up-to-two expected net | Expected net gain | Raw XI net change | Selection utility gain |
| --- | ---: | ---: | ---: | ---: | ---: |
| gw9-2199732 | 174.8501732043 | 175.0072799233 | 0.1571067189 | -0.2145526416 | 0.1571067189 |
| gw9-3832237 | 147.7025912958 | 148.2388375621 | 0.5362462663 | -0.8683706450 | 0.5362462663 |
| gw9-5349883 | 165.9333394108 | 166.3692317528 | 0.4358923421 | -0.2290903208 | 0.4358923421 |

For these inputs, discount is 1, terminal resource values are zero, and the changed plans
incur no paid-transfer hits. Thus selection utility equals scored expected net points in the
changed cases. Their raw XI projections decrease while appearance/autosub/vice-aware net
points increase. The difference here is the scoring basis, not a resource-value trade-off.
The wrapper's selected optional label remains `initial_single_swap`; the research proposal's
`optional.phase` and `optional.incoming` expose its true arity.

All rescored plans are unproved globally, with null global bounds/gaps. The restricted pool
and captured baseline forecast do not establish a benefit in the served unrestricted
football model. No Phase 6 qualification decision or owner approval is inferred.

### Per-case controls

| Member-week | Scenario | 1w seconds | 1w status / gap | 3w seconds | 3w status / gap |
| --- | --- | ---: | --- | ---: | --- |
| gw8-2199732 | wildcard | 5.058 | OPTIMAL / 0.000 | 18.908 | OPTIMAL / 0.000 |
| gw8-2281624 | freehit | 16.299 | OPTIMAL / 0.000 | 19.384 | OPTIMAL / 0.000 |
| gw8-313686 | normal | 2.212 | OPTIMAL / 0.000 | 9.483 | OPTIMAL / 0.000 |
| gw8-3832237 | tight_bank | 30.315 | OPTIMAL / 0.000 | 29.189 | OPTIMAL / 0.000 |
| gw8-4287206 | conflicting_instructions | 0.086 | INFEASIBLE / n/a | 0.805 | INFEASIBLE / n/a |
| gw8-5081114 | normal | 3.465 | OPTIMAL / 0.000 | 12.987 | OPTIMAL / 0.000 |
| gw8-5349883 | wildcard | 24.730 | OPTIMAL / 0.000 | 25.848 | OPTIMAL / 0.000 |
| gw8-5662073 | freehit | 20.935 | OPTIMAL / 0.000 | 8.097 | OPTIMAL / 0.000 |
| gw8-6654210 | tight_bank | 3.907 | OPTIMAL / 0.000 | 20.055 | OPTIMAL / 0.000 |
| gw8-6879786 | conflicting_instructions | 0.082 | INFEASIBLE / n/a | 0.849 | INFEASIBLE / n/a |
| gw9-2199732 | wildcard | 2.427 | OPTIMAL / 0.000 | 40.334 | OPTIMAL / 0.000 |
| gw9-2281624 | freehit | 3.208 | OPTIMAL / 0.000 | 9.226 | OPTIMAL / 0.000 |
| gw9-313686 | normal | 2.550 | OPTIMAL / 0.000 | 20.414 | OPTIMAL / 0.000 |
| gw9-3832237 | tight_bank | 26.463 | FEASIBLE / 6.251 | 36.492 | OPTIMAL / 0.000 |
| gw9-4287206 | conflicting_instructions | 0.126 | INFEASIBLE / n/a | 0.812 | INFEASIBLE / n/a |
| gw9-5081114 | normal | 3.493 | OPTIMAL / 0.000 | 11.022 | OPTIMAL / 0.000 |
| gw9-5349883 | wildcard | 8.114 | OPTIMAL / 0.000 | 19.810 | OPTIMAL / 0.000 |
| gw9-5662073 | freehit | 4.291 | OPTIMAL / 0.000 | 23.970 | OPTIMAL / 0.000 |
| gw9-6654210 | tight_bank | 4.371 | OPTIMAL / 0.000 | 15.408 | OPTIMAL / 0.000 |
| gw9-6879786 | conflicting_instructions | 0.082 | INFEASIBLE / n/a | 0.850 | INFEASIBLE / n/a |

### Per-case expected-point comparisons

Gains are experimental minus single-swap baseline. `n/a` is a failed comparison, not zero.

| Member-week | Full optional outcome | Full expected net gain | Restricted proposal arity | Restricted expected net gain | Restricted raw XI net gain | Restricted utility gain |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| gw8-2199732 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 | 0.000000 |
| gw8-2281624 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 | 0.000000 |
| gw8-313686 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 | 0.000000 |
| gw8-3832237 | ERROR | n/a | 2 | 0.000000 | 0.000000 | 0.000000 |
| gw8-4287206 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 | 0.000000 |
| gw8-5081114 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 | 0.000000 |
| gw8-5349883 | evaluated, original retained | 0.000000 | 2 | 0.000000 | 0.000000 | 0.000000 |
| gw8-5662073 | skipped | 0.000000 | 2 | 0.000000 | 0.000000 | 0.000000 |
| gw8-6654210 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 | 0.000000 |
| gw8-6879786 | skipped | 0.000000 | 2 | 0.000000 | 0.000000 | 0.000000 |
| gw9-2199732 | skipped | 0.000000 | 2 | 0.157107 | -0.214553 | 0.157107 |
| gw9-2281624 | skipped | 0.000000 | 2 | 0.000000 | 0.000000 | 0.000000 |
| gw9-313686 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 | 0.000000 |
| gw9-3832237 | ERROR | n/a | 2 | 0.536246 | -0.868371 | 0.536246 |
| gw9-4287206 | skipped | 0.000000 | 2 | 0.000000 | 0.000000 | 0.000000 |
| gw9-5081114 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 | 0.000000 |
| gw9-5349883 | evaluated, original retained | 0.000000 | 2 | 0.435892 | -0.229090 | 0.435892 |
| gw9-5662073 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 | 0.000000 |
| gw9-6654210 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 | 0.000000 |
| gw9-6879786 | skipped | 0.000000 | 2 | 0.000000 | 0.000000 | 0.000000 |

### Validation and handoff

- Ruff lint passes; Ruff format confirms 1,662 files already formatted.
- Mypy passes on 448 source files.
- Import Linter keeps all 11 contracts through its installed interpreter entry point:
  `python -c "from importlinter.cli import lint_imports_command; lint_imports_command()"`.
- Full `pytest -q -n auto --dist loadscope`: **15,606 passed, 88 skipped, 11 warnings**,
  **424.42 seconds**, Python 3.13.5 on Windows. No slow-test deselection. All 17 research
  test cases are included. Skips cover platform-specific and archived-capture tests,
  optional dependencies and opt-in browser/container/capacity probes.
- A fresh first-member replay matches all eight pricing jobs, two window controls, both
  full-pool arms and both restricted-pool arms: **14 plan comparisons**. Matched fields
  include objectives, bounds, proof, raw/scored points, selection utility, all weekly
  squads/roles/transfers/resources, deterministic work and call/thread counts. Elapsed
  times and wall allocations derived from elapsed time are excluded. Commands use
  `benchmark --limit 1 --output .codex-tmp/phase1-v2-reproduction` and
  `neighborhood --limit 1 --output .codex-tmp/phase1-v2-neighborhood-repro.json`, with the
  module prefixes above. Separate output and receipt directories preserve the primary record.
- All 40 controls reproduce the prior run's objective, bound, gap, status, proof and call
  count. The corrected pair experiment and point labels use the complete new run.
- CI at `9dfbf04b5afaa221a1d6a8555c399f06d70b922d` passes the full Python 3.11/3.13 gates,
  web checks, container smoke and device engines on Chromium, Firefox and WebKit. The final
  record commit starts its own CI; consult the draft PR for that result.

A clean-checkout CI failure exposed the new queue test's dependence on an already-built
probe directory. The test now uses its own temporary root. A separate local retry initially
used an overly long temporary root: 52 existing fixture paths reached 264-276 characters and
failed Windows file creation. The complete suite passed with a short, unique temporary root.
Neither correction changes the measurement source, fixed inputs or product behaviour.

Only Phase 1 research, frozen fixtures, records and tests changed. Product source, public
contracts and the published site/backend remain unchanged. No merge-queue entry or deployment
was made. Later phases remain pending. Required independent review is tracked on the draft
PR; the phase stops for owner review.
