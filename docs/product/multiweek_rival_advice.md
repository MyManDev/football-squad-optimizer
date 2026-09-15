# Multi-week rival advice

Policy: first_week_rival_horizon_v1.

A member may compare saf-puan, ortak-koru and fark-yarat over three or five
gameweeks. Only the first decision is committed by this recommendation; future
weeks are a conditional continuation, recomputed when a new capture arrives.

## Shared decision rules

All three arms use the same capture, projection horizon, held squad, prices,
free transfers, transfer penalties, bench weight and deterministic solve budget.
Keep the existing multi-week policy: at most one transfer each week, no chips
offered, frozen prices and the existing fixture-scaled projections. Existing
one-week recommendations and multi-week saf-puan remain unchanged.

The rival reference is the deadline-available captured starting eleven. The
constraint counts those players in our first-week **fifteen**, not our starting
eleven. Ortak-koru uses the catalogue floor and fark-yarat its ceiling. Neither
constraint applies to later weeks. A target is never silently relaxed.

Missing rival inputs, proven infeasibility, no solution within the budget and
infrastructure failure are different outcomes. FEASIBLE plans may be served with
their measured gap under the existing deterministic-budget rule. A wall-clock
cutoff cannot be published as a reproducible plan.

If the picks provider restored a rival's pre-Free-Hit squad, that restored squad
cannot stand in for the captured XI. This version reports missing rival inputs.

## Comparison

Report first-week net points separately from the sum of projected starting-eleven
and captain points less actual hit charges across the window. The signed difference
is `control_total - strategy_total`: positive means points given up, matching the
one-week direction. It is a comparison of returned plans, not a
proof of the strategy's true cost or a confidence interval. Bench weight and the
solver's transfer caution belong to its objective, not the displayed net-points sum.

Publish `expected_points_cost = max(0, control_total - strategy_total)` and
`expected_points_cost_ceiling` beside it. The ceiling converts the control's solver
bound to the displayed net basis: allow for the maximum transfer caution margin,
negative bench contributions and integer rounding, and cap it by the relaxed
roster upper bound. Discounted policies use the relaxed roster bound directly.
The card labels the ceiling as a ceiling even when the objective solve is OPTIMAL.
No extra pricing solve is added. Existing saf-puan payloads remain byte-compatible.

Record the policy id, rival id and captured gameweek, overlap target and achieved
count, both net totals and both solver statuses/gaps. Preserve the old payload
when serving saf-puan. Do not repurpose the member_week_horizon_v1 measurement
contract: it describes evidence accumulation, not transfer-plan windows.

The existing gap-and-weeks suggested-strategy label is a one-week rule. It is not
promoted to a multi-week recommendation by this feature. No win probability,
future rival transfer forecast or new player model is introduced.

## Publication and transport

The published index describes actual files and explicit unavailability. Build a
bounded static menu for the default rival; other rival/window combinations can
use the existing backend queue. Reuse the member/window control within a batch.
A catalogue entry alone never establishes a published or computable answer.

The cache identity includes the complete request and server context. Duplicate
requests share a job; changing rival or window must not reuse the wrong answer.
A long-running job stays addressable after the browser stops waiting. Static
fallback remains visibly distinct from the requested computed answer.

## Integration

The existing `advise_entry` entry point serves both the batch publisher and the
worker. `build_window_payload` passes `FirstWeekOverlap` into `plan_transfer_horizon`;
the existing optimizer applies it to `squad_vars[0]`. No additional solver, queue,
database or forecast model is introduced.

`window_comparison` is an additive object in `advice_read_v1`. Python validates its
identity, bounds, consecutive weeks and net arithmetic before caching and reading.
The browser mirrors these checks. The comparison is also retained in the member
advice record, alongside the published payload digest.

`render_member` reuses each member/window control and publishes longer rival plans
only for the default rival. Exact rival paths and their default aliases contain the
same bytes. The index lists successful windows and records explicit refusals. Static controls
filter windows by the selected rival's actual file path. Python validates overlap
limits from STRATEGY_CATALOG; the browser checks the declared band's shape and
whether the achieved overlap satisfies it, without another hard-coded 9/5 policy.

SolverExecutionError is caught at each member/control/rival-window boundary;
a failed solve records SOLVER_EXECUTION_FAILED and does not abort other members.
Multiweek product refusals publish only their stable code, without diagnostics.
The main bilingual MESSAGES catalog owns the new copy. Both rendered rival-window
cards and actual generated 3/5-week rival documents are swept by the honesty guards.

The API read/submit capability checks accept the same 1/3/5 windows as the producer.
The existing request/cache identity separates member, rival, window, capture,
handoff, revision and configuration; the configuration includes this policy id.
The worker maps product refusals to `WINDOW_INFEASIBLE`, `WINDOW_NO_SOLUTION` or
`WINDOW_INPUTS_UNAVAILABLE`. Infrastructure failures remain worker failures.

With a backend, the web permits valid unpublished combinations to be requested.
After five minutes it preserves the current job and offers to resume polling that
job, without another submission. Changing selection cancels the old browser wait.
The first-week suggested-strategy rule is hidden on longer windows. Both plan
statuses are shown; FEASIBLE controls use the existing whole-window bound explanation.

The opt-in browser test starts a real API and worker, sends 1/3/5-week requests,
reads the result and repeats the request from cache. It also checks mobile overflow
and keyboard accessibility. The capacity probe supports
`SQUADOPT_CAPACITY_WINDOW=5` with its existing dedup, distinct and cache-hit scenarios.

## Acceptance and release

- Same inputs reproduce the same semantic answer under a fixed metadata clock.
- Existing one-week and saf-puan reference outputs stay unchanged.
- Every week satisfies budget, squad, position and transfer rules.
- First-week overlap binds where requested and is absent later.
- Net totals equal per-week points minus hits, without double counting.
- Producer, runtime validator, API, worker, cache and browser agree on identity.
- Invalid/missing/unavailable results cannot masquerade as successful advice.
- Measure cold solve, cache hit and bounded concurrent requests before enabling.
- Run the complete Python and web gates and final browser/API/worker E2E checks.

Deployment and new published production data are separate operational actions.
Disable the new multi-week capabilities to roll back; never erase historical
advice or measurement records. Week-specific model research and an automatic
multi-week strategy selector are outside this first release.
