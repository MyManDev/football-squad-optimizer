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

Publish and retain the completed required-rule plan before searching for an
alternative. Its transfers, lineup and score stay fixed. Within the same worker
and reservation, exclude that squad and seek at most two other decisions.
Each alternative shares 15 seconds across model construction and its resource
tie breaks, within the original 120-second worker ceiling. Pass the smaller
remaining limit to HiGHS. A timeout, inconsistent alternative, late worker
failure or reload preserves the last checked answer. A stale worker cannot
replace the result of another confirmation.

Pin the execution location in the confirmation. A run containing an unsupported rule
stays entirely on the service. Before each worker attempt reserve four native units
durably from the existing 84-unit one-week capacity; a completed cache hit reserves none.
Before pinning a new confirmation to the device, persist and read back the zero-unit
receipt for the actual run and verified inputs. Reserve space for a two-digit unit
count. If capacity cannot be retained at confirmation, pin the entire run to the
server, using the same durable identity and ordinary server admission. History can
retain that identity when session storage is unavailable. If both identity stores
fail, open no job. A run already pinned to the device still needs its durable receipt
before starting each worker. It cannot switch to a second budget midway.

Retain at most eight device answer envelopes per tab, covering two complete menus of
four results. Evict the oldest stored answer when a new answer exceeds the count or
the browser quota. Session records, capacity receipts and unrelated browser data are
never eviction candidates. The current in-memory answer remains usable if persistence
fails. These cache limits affect only device results.

## One-week preference execution

The private device request carries the same closed preference bundle as Phase 3.
The main and the preference bundle are separate bounded worker attempts, each charged
four units before starting. Every internal solve of one attempt shares the existing
120-second ceiling; layers and individual prices do not create service jobs.

In total-allowance mode use the main plan shown for this run as the reference.
The private worker receives its squad, starters, captain and proof status from the
matched device cache. It checks those decisions against the current pinned inputs
and required rules, then recomputes J with the integer net-points coefficients.
A feasible main decision with no optimality proof supplies J with
`reference_proved: false`. A missing or invalid reference cannot establish J.
Ordinary device requests and individual-price execution keep their existing proof
requirements. Preserve the main answer in the returned envelope and put computed
components in the existing result contract.
A total allowance skips individual pricing, binds one integer-scaled net-points floor,
maximizes up to three canonical priority counts in order, freezes each completed count,
and finally maximizes net points. Finite variable bounds determine every implication
coefficient. Equal priority never acquires a writing-order weight.

Both solvers accept a feasible count witness that demonstrably satisfies every rule
in the current layer: its count attains the exact upper bound. Otherwise only a
proved count may be frozen. Keep the highest-scoring known decision at equal
proved counts. Leave a quarter of the remaining search allowance for the points
pass over the completed counts, including after an interrupted weaker layer.
A wall-time cutoff during the points pass retains the earlier witness. A feasible
points result stopped by a deterministic work cap may improve that witness after
checking its constraints and score. Either incomplete points pass reports
`budget_exhausted: true` unless a subsequent points pass proves the optimum.
HiGHS distinguishes an iteration limit from the device worker's wall-time limit.
Only the explicit iteration-limit status qualifies for a deterministic stop. Computed preference
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
