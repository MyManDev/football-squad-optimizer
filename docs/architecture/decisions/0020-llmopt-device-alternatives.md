# ADR 0020: Bounded one-week device alternatives

- Status: proposed
- Date: 2026-11-19
- Decider: project owner
- Related: ADR 0019; PR #1467

## Decision

First add explicit hard-rule constraints to the one-week device model. Keep the page's
server routing until twenty frozen Phase 1 member-weeks agree with the server objective.
Different decisions require an equal objective, not an assertion that they look similar.
Unverified rule families remain on the server. The incomplete priority transport from
Phase 3 is not silently treated as device support.

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
