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
or that the historical member chose that chip.

Both 1- and 3-week controls use published points, the planner's net-points preference and
current game transfer limits. Later weeks repeat points scaled by captured fixture counts,
as the existing publication replay runner does. Controls include build and result-reading
time. Times are sequential local elapsed seconds, not production service or queue latency.
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
native HiGHS child call is counted separately. The solver uses one search thread. A job is a
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

The optional experimental proposal considers singles plus pairs from a fixed shortlist of
24 highest point proxies and 8 largest cash releases. It tests whole-package bank, club,
required players, hit and transfer limits, then validates one selected first squad with the
full horizon planner. Cash-releasing moves can enter even if individually unattractive.
The member policy is preserved: the second move requires two banked free transfers. This
experiment does not relax the one-transfer policy to admit paid two-move packages.
It is a proxy shortlist, not exhaustive package search. Actual candidate checks and lineup
work are disclosed. A failed package can lose an optional opportunity; neither arm is silently
given the other arm's extra solve. Gains are paired expected net points and the wrapper's own
discounted selection utility, never realised points. No rescored result gets a global
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
digest. Detailed receipts in ignored `artifacts/llmopt_phase1/` carry plans, resource transitions,
raw solver status/bounds and per-call counts. They are regenerated evidence, not the committed
record (ADR 0003). Alternate `--output` paths write their own `summary.json` and cannot replace
the committed summary. `--resume` accepts only identical committed code and input digests;
partial cases are never aggregated. After an existing expected-window accounting refusal
halted the first complete run at the fourth case, the harness gained explicit failure
recording. `--reuse-completed` preserves the first three complete cases from `a5e308d5e`
without rerunning or selecting them by score; it requires the same input digest and unchanged
product/replay-builder code. Each case names its actual producing program in the summary's
`measurement_programs` map. The other cases run with the failure-recording revision. The
solver, candidate rules and configured budgets did not change. Known accounting and wall-limit
refusals have status `ERROR` and null gain; other exceptions still stop the measurement.
Wall times naturally vary between repetitions.

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
7. How should Phase 6 qualification read a restricted-pool case whose undiscounted net
   points decrease while the current selection utility increases? The two metrics must
   not be silently substituted for one another, or for a full-pool operational benefit.

## Results and phase handoff

The run covers **20 member-weeks and 40 window controls**, with four of each control scenario.
All solver invocations observed in the receipts use one search thread. This is a descriptive
local replay with one observation per condition, not a production latency or forecast-quality claim.

| Window | Optimal | Feasible, unproved | Infeasible | Seconds, min / median / max |
| --- | ---: | ---: | ---: | --- |
| 1 week | 15 | 1 | 4 | 0.082 / 3.704 / 29.921 |
| 3 weeks | 16 | 0 | 4 | 0.791 / 17.058 / 40.017 |

All 31 optimal controls have a zero model gap. The eight infeasible controls carry no
objective or gap. `gw9-3832237`, the one-week zero-bank control, is **FEASIBLE**, not proved:
incumbent **52.310**, best bound **58.561**, absolute gap **6.251 points**. This is an observed
example for the later J decision, not permission to call the incumbent optimal. Timed-out
incumbents and wall times can vary when the same fixed inputs and current limits are rerun.

### Individual pricing workload

| Member-week | Window | Local backend jobs | CP-SAT calls | Native calls | Total solver calls | Total computation seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gw8-313686 | 1 | 4 | 12 | 0 | 12 | 7.604 |
| gw8-313686 | 3 | 4 | 12 | 4 | 16 | 45.180 |
| gw9-313686 | 1 | 4 | 12 | 0 | 12 | 8.599 |
| gw9-313686 | 3 | 4 | 12 | 4 | 16 | 99.384 |

Across these four cold queue runs: **16 jobs, 48 CP-SAT calls, 8 native calls, 56 solver
invocations**. Total model computation is **160.767 seconds**. The third, unbounded no-hit
preference is unslotted individually and enters the combined request. These are four-job
runs even where several results agree; this does not establish reload, cancellation or
whole-run idempotency guarantees. Computation includes model construction and reading its
result; HTTP, polling and queue/orchestration overhead are outside these totals.

### Full-pool comparison

Both arms finish in 18 of 20 cases. Their selected expected net points and selection utilities
are identical in all 18. In **16 cases** the wrapper never invokes the optional proposal because
the original construction routes do not meet its completion gate. In **2 cases** an optional
proposal is evaluated; the retained original plan remains selected. One of those two cases
evaluates an actual two-move proposal in the experimental arm. Thus zero paired gain is
not evidence that all two-move packages have zero value.

The remaining two cases fail the unchanged wrapper's deterministic-work accounting in both
arms: `gw8-3832237` records **24.0587449622 / 24.0** units in a proposal phase and
`gw9-3832237` records **24.2239097074 / 24.0**. These are phase-cap refusals, not claims
that the whole 60-unit budget was spent. Their gains are **null**, not zero. Production
code and the tolerance were not changed.

### Restricted-pool diagnostic

The separate pool contains **33 to 36 players** per member-week. Optional refinement is
reached in both arms on all 20 cases, using the same 60-unit and 1,153-lineup-evaluation
ceilings. Nineteen cases have zero difference in both reported metrics. In `gw9-5349883`,
the experimental arm selects a different path:

- Expected net points: **161.3563899963 to 161.1272996755**, a **-0.2290903208** change.
- The current discounted, resource-valued selection utility: **+0.4358923421**.

This is a trade-off between the reported metrics, not an unqualified improvement or
deterioration. The unchanged wrapper still labels its selected optional plan
`initial_single_swap`; `optional.phase` and `optional.incoming` disclose the research
proposal's actual arity. Both arms' rescored plans remain unproved globally and carry
null global bounds/gaps. The small pool and saved baseline forecast are not the served
football model's unrestricted decision space. This record makes no Phase 6 eligibility
decision and gives no owner approval.

### Per-case results

`n/a` for an infeasible gap means no incumbent. `ERROR` in the comparison means no paired
value, not a zero gain. The compact JSON additionally gives every control's objective and
best bound, each arm's time and call count, actual work and the producing program.

| Member-week | Control scenario | 1w seconds | 1w status / gap | 3w seconds | 3w status / gap |
| --- | --- | ---: | --- | ---: | --- |
| gw8-2199732 | wildcard | 5.093 | OPTIMAL / 0.000 | 18.786 | OPTIMAL / 0.000 |
| gw8-2281624 | freehit | 16.276 | OPTIMAL / 0.000 | 19.257 | OPTIMAL / 0.000 |
| gw8-313686 | normal | 2.219 | OPTIMAL / 0.000 | 9.488 | OPTIMAL / 0.000 |
| gw8-3832237 | tight_bank | 29.921 | OPTIMAL / 0.000 | 29.225 | OPTIMAL / 0.000 |
| gw8-4287206 | conflicting_instructions | 0.082 | INFEASIBLE / n/a | 0.811 | INFEASIBLE / n/a |
| gw8-5081114 | normal | 3.502 | OPTIMAL / 0.000 | 13.049 | OPTIMAL / 0.000 |
| gw8-5349883 | wildcard | 24.746 | OPTIMAL / 0.000 | 25.974 | OPTIMAL / 0.000 |
| gw8-5662073 | freehit | 20.830 | OPTIMAL / 0.000 | 8.094 | OPTIMAL / 0.000 |
| gw8-6654210 | tight_bank | 3.905 | OPTIMAL / 0.000 | 20.071 | OPTIMAL / 0.000 |
| gw8-6879786 | conflicting_instructions | 0.082 | INFEASIBLE / n/a | 0.791 | INFEASIBLE / n/a |
| gw9-2199732 | wildcard | 2.355 | OPTIMAL / 0.000 | 40.017 | OPTIMAL / 0.000 |
| gw9-2281624 | freehit | 3.159 | OPTIMAL / 0.000 | 9.179 | OPTIMAL / 0.000 |
| gw9-313686 | normal | 2.499 | OPTIMAL / 0.000 | 20.124 | OPTIMAL / 0.000 |
| gw9-3832237 | tight_bank | 26.333 | FEASIBLE / 6.251 | 36.176 | OPTIMAL / 0.000 |
| gw9-4287206 | conflicting_instructions | 0.083 | INFEASIBLE / n/a | 0.796 | INFEASIBLE / n/a |
| gw9-5081114 | normal | 3.469 | OPTIMAL / 0.000 | 11.003 | OPTIMAL / 0.000 |
| gw9-5349883 | wildcard | 8.013 | OPTIMAL / 0.000 | 19.635 | OPTIMAL / 0.000 |
| gw9-5662073 | freehit | 4.266 | OPTIMAL / 0.000 | 23.898 | OPTIMAL / 0.000 |
| gw9-6654210 | tight_bank | 4.405 | OPTIMAL / 0.000 | 15.331 | OPTIMAL / 0.000 |
| gw9-6879786 | conflicting_instructions | 0.084 | INFEASIBLE / n/a | 0.810 | INFEASIBLE / n/a |

| Member-week | Full-pool optional outcome | Full net gain | Restricted optional arity | Restricted net gain | Restricted utility gain |
| --- | --- | ---: | ---: | ---: | ---: |
| gw8-2199732 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 |
| gw8-2281624 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 |
| gw8-313686 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 |
| gw8-3832237 | ERROR | n/a | 1 | 0.000000 | 0.000000 |
| gw8-4287206 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 |
| gw8-5081114 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 |
| gw8-5349883 | evaluated, original retained | 0.000000 | 2 | 0.000000 | 0.000000 |
| gw8-5662073 | skipped | 0.000000 | 2 | 0.000000 | 0.000000 |
| gw8-6654210 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 |
| gw8-6879786 | skipped | 0.000000 | 2 | 0.000000 | 0.000000 |
| gw9-2199732 | skipped | 0.000000 | 2 | 0.000000 | 0.000000 |
| gw9-2281624 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 |
| gw9-313686 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 |
| gw9-3832237 | ERROR | n/a | 1 | 0.000000 | 0.000000 |
| gw9-4287206 | skipped | 0.000000 | 2 | 0.000000 | 0.000000 |
| gw9-5081114 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 |
| gw9-5349883 | evaluated, original retained | 0.000000 | 2 | -0.229090 | 0.435892 |
| gw9-5662073 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 |
| gw9-6654210 | skipped | 0.000000 | 1 | 0.000000 | 0.000000 |
| gw9-6879786 | skipped | 0.000000 | 2 | 0.000000 | 0.000000 |

### Validation and handoff

- `ruff check .`: passed.
- `ruff format --check .`: 1,662 files already formatted.
- `mypy`: no issues in 448 source files.
- Import Linter: 11 contracts kept, 0 broken, through the installed console entry point
  `python -c "from importlinter.cli import lint_imports_command; lint_imports_command()"`.
  The Windows executable launcher returned no output in the sandbox; the same CLI entry
  point executed successfully through the interpreter.
- Full `pytest -q -n auto --dist loadscope`: **15,598 passed, 88 skipped, 11 warnings**, 420.48 s
  on Python 3.13.5 / Windows. No slow-test deselection. Skips include POSIX-only host tests,
  archived-capture tests, optional dependencies and opt-in browser/container/capacity probes.
  The nine new research tests are included in the passing full suite.
- A fresh first-member replay matches all eight pricing jobs, both window controls, both
  full-pool arms and both restricted-pool arms on objectives, bounds, proof status,
  decisions/resources and solver-call counts. Wall times are deliberately excluded.
  Reproduction writes separate compact summaries under `.codex-tmp`; committed results stay
  unchanged. Commands: `benchmark --limit 1 --output .codex-tmp/phase1-reproduction` and
  `neighborhood --limit 1 --output .codex-tmp/phase1-neighborhood-reproduction.json`, using
  the module prefixes in the reproduction section.

Only Phase 1 research, frozen fixtures and their tests were added. Product code, public
contracts and the published site/backend were not changed. No merge-queue entry or deployment
was made. Later phases remain pending; the required independent review and owner review are
still outstanding.
