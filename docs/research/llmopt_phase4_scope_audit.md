# One-week scope audit

The original keep-first-held-player probe does not prove the original Phase 1 control
scope. This additional [record](llmopt_phase4_scope_audit.json) uses all twenty immutable
member-weeks without that extra rule. Its committed producer is
`0eb052c141e82c482c2fe0874e90212036382c52`; rerun with
`python -m docs.research.llmopt_phase4.audit`, separately from tests.

| Profile | Cases | Equal feasible objectives | Both infeasible | Equal transfer decisions |
| --- | ---: | ---: | ---: | ---: |
| Exact original Phase 1 controls and solver settings | 20 | 15/16 | 4 | 15/16 |
| Same controls, active preference server settings | 20 | 16/16 | 4 | 16/16 |
| Active preference settings, no added player rule | 20 | 20/20 | 0 | 20/20 |

The four missing numeric objectives in the first two profiles are proved infeasible,
not numeric matches. No differing transfer decision is described as an equal-score tie:
the sole difference is a score difference. Every original control replays its frozen
status and value, **20/20**. Both tight-bank members retain zero bank in all profiles.
Forced Wildcard and Free Hit and the original hold-plus-include contradictions remain
in both control profiles. No artificial keep constraint is added.

The exception is **GW9, entry 3832237, zero bank**. The original 20-unit, default
linearization control returns **52.310 FEASIBLE**, bound **58.561**, exactly as frozen.
The device proves **52.978**, a difference of **+0.668**. The active preference server
profile, also at 20 units but linearization 2, independently proves **52.978** with the
same transfer decision. This is not parity with the original 52.310 incumbent, and the
frozen reference is not replaced. It is not a realized-points quality claim.

The owner approved the active server preference profile as the acceptance criterion.
Its 16/16 feasible matches plus four matching infeasibilities and 20/20 no-added-rule
matches satisfy that criterion. The proved 52.978 active result is not a failure
because the older unproved incumbent was 52.310. Both observations remain in the
record; no frozen Phase 1 value or numerical comparison has been overwritten.

The active one-week LLMOPT path already selects net points and linearization 2 on the
server. Its profile is the relevant matched comparison for new device confirmations.
Old confirmed server sessions retain their pinned location. Other model choices,
scenarios, future-week rules and unverified chip-preference combinations continue to
use the server. This audit covers mandatory rules; the completed Phase 3 priority
transport requires its own device comparison before migration is claimed.

The device probe calls the actual complete `solvePlan`, including hold-score and
publication, with a cumulative **120-second** ceiling. Maximum complete answer time
was **2.224 seconds**. Sequential totals were 161.21/8.63 seconds for original-control
server/device calls, 19.31/8.47 for active-control calls, and 24.98/14.24 for active
no-added-rule calls. These are descriptive local timings under different orchestration,
not live latency measurements. No solver allowance was raised and no reference was
warm-started to force agreement. The 60 comparisons opened **zero server jobs** and
used no live endpoint; tests and CI were not running during measurement.

## Priority migration

The Phase 3 public program is complete and independently measured through its API and
worker. This mandatory-rule audit does not itself establish the remaining one-week
priority migration. The separate [priority comparison](llmopt_phase4_priority_audit.md)
now supplies that evidence: 16/16 feasible objectives and priority outcomes plus four
matching infeasibilities, with eight differing equal-score transfer decisions.
Tiny exhaustive tests and the existing capacity are retained.
See [ADR 0020](../architecture/decisions/0020-llmopt-device-alternatives.md).
