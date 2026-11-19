# ADR 0020: Bounded one-week device alternatives

- Status: accepted
- Date: 2026-11-19
- Decider: project owner
- Related: ADR 0019; PR #1467

## Decision

Hard-rule-only one-week menus explicitly use the existing `net_points_priority`
objective for both main and alternatives. The local request marker is not serialized to
the service. Legacy preferred-rule pricing keeps its existing objective and ceilings.

First add explicit hard-rule constraints to the one-week device model. Keep the page's
server routing until twenty frozen Phase 1 member-weeks agree with the server objective.
Different decisions require an equal objective, not an assertion that they look similar.
Unverified rule families remain on the server. Phase 3's complete public preference
execution is the starting point for this phase's one-week worker transport.

Alternative identity is the transfer decision: the sorted resulting squad and chip.
Changing only starters or captain does not create another option. Exclude each previous
squad with a no-good cut. Keep hard constraints on every solve. Show at most three
non-dominated decisions within the chosen net-points gap, comparing net points, bank,
hit charges and remaining free transfers. Equal resource vectors do not dominate each
other; duplicate transfer identities do.

The initial gap is **6.3 points**, rounding the frozen Phase 1 maximum one-week gap
6.251 upwards to the page's one-decimal precision. This is an explicit initial product
bound, not measured evidence that alternative plans improve football outcomes.

Device alternatives create no server jobs. An unproved device search cannot be called
an equivalent solution. Preserve the main answer and report incomplete integration
instead of opening an unbudgeted fallback alternative job.

Pin the execution location in the confirmation. A run containing an unsupported rule
stays entirely on the service. Before each worker attempt reserve four native units
durably from the existing 84-unit one-week capacity; a completed cache hit reserves none.
Refuse a new worker if the capacity receipt cannot be read or written. This intentionally
requires session storage for new device work, even when the run identity alone could
survive in history state. The owner approved refusing new work when this receipt
cannot be persisted.

## One-week preference execution

The private device request carries the same closed preference bundle as Phase 3.
The main and the preference bundle are separate bounded worker attempts, each charged
four units before starting. Every internal solve of one attempt shares the existing
120-second ceiling; layers and individual prices do not create service jobs.

Recompute the required main objective from the same verified published inputs inside
the preference attempt. Device main answers require a proved solve, so this objective
is not a provider number or a client-supplied numeric reference. Preserve the main
answer in the returned envelope and put computed components in the existing result
contract. Ordinary prices retain their existing zero-floor cost and acceptance masks.
A total allowance skips individual pricing, binds one integer-scaled net-points floor,
maximizes up to three canonical priority counts in order, freezes each completed count,
and finally maximizes net points. Finite variable bounds determine every implication
coefficient. Equal priority never acquires a writing-order weight.

Retain the last completed witness if the shared ceiling ends; an incomplete layer or
points tie break cannot replace it. Publishing that retained witness uses its existing
decisions and arithmetic, without an unconstrained re-solve. Computed preference
proof metadata stays separate from the unrestricted main plan's proof. Request and
private result extensions are documented in `llmopt_device_v1.schema.json` in this PR.
The model interpretation schema and credential handling do not change.

## Original-control audit

The original 40/40 keep-first-held-player probe does not prove the unconstrained or
original-control scope. The additional [scope audit](../../research/llmopt_phase4_scope_audit.md)
replays every original Phase 1 control unchanged, then compares the active preference
profile separately. The active 20-unit, linearization-2 net-points profile matches the
device in 16/16 feasible controls plus four infeasibilities, and 20/20 no-added-rule
cases. New local confirmations retain that matched profile; old server confirmations
are not upgraded during reload. Unverified rule families remain on the server.

The owner approved equality with the server's active preference settings as the
acceptance criterion: 16/16 feasible controls plus four matching infeasibilities,
and 20/20 no-added-rule cases. GW9 entry 3832237 at zero bank has a frozen unproved
52.310 under default linearization, while the active server and device prove 52.978.
The two numbers remain different observations; the stronger proved active result is
not an acceptance failure. The frozen Phase 1 value stays unchanged. No allowance,
accounting tolerance or required equality check is enlarged.

The one-week priority migration must separately compare the same twenty member-weeks
and tiny independently enumerated transfer packages. Unsupported production rule
families retain their service routing and are named in the phase report rather than
being counted as a completed device handoff.
