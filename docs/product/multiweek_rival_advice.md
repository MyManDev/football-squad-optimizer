# Multi-week rival advice

Policy: first_week_rival_horizon_v1. Implementation in progress on a feature branch.

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

## Comparison

Report first-week net points separately from the sum of projected starting-eleven
and captain points less actual hit charges across the window. The signed difference
against the same-window saf-puan control is a comparison of returned plans, not a
proof of the strategy's true cost or a confidence interval. Bench weight and the
solver's transfer caution belong to its objective, not the displayed net-points sum.

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

