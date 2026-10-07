# Published fixture difficulty: 2026-27 live protocol

Issue #1009 part (b), step 1. This protocol freezes Decisions 5 and 6 before any
live comparison is read. It changes no producer, handoff, device table or member
page. It does not rerun the development study or open the locked 2025-26 holdout.

## Binding start and one verdict

The target is a merge before the GW7 deadline, `2026-10-17T10:00:00Z`, either
before that Friday run starts or after its publish finishes. A docs-only merge
must also wait while a weekly run is in progress. The first scored week is the
first 2026-27 deadline strictly after this protocol's merge time. A week whose
deadline is at or before that merge is excluded, even if it settles later.
The record stores merge commit, merge instant and the resulting first week.

The population ends at GW20, whose deadline is `2027-01-05T18:00:00Z`.
There is exactly one verdict, after a captured calendar shows every GW20 fixture
`finished` and `data_checked`. The verdict names the earliest eligible settled
capture and its fingerprint. A runner refuses real-week comparisons before that
condition. Synthetic tests may run earlier. No interim error, ordering or squad
comparison is printed, and no threshold changes after live data is read.

## Paired inputs and comparator

For each eligible week, use the latest `fpl-live` capture before its deadline
whose next open deadline is that week. The same immutable capture supplies both
arms, the full roster, prices, positions, availability and published fixture
difficulty. Record capture id, instant, fingerprint and all required payload
hashes. A candidate cannot draw a rating from an archive or a later capture.

The base is the exact `current` projection served for that capture, not the
development control. Pair with exactly one stored handoff using
`handoff_fingerprint_for` in `src/squadopt/platform/capture_context.py`, over the
owner-selected weekly handoff root. Record handoff version, fingerprint and file
hash. Apply the captured availability through `project` in
`src/squadopt/live/recommendation.py`, as the live reader does. This is an offline
read of stored inputs and needs no backend process.

If DEFCON, `ep_next` or another approved projection ships during the population,
the base remains each week's actually served version. Report pooled readings
and counts and readings for each handoff version. Do not replace earlier weeks
with a later model. The #988 route choice does not alter the pairing rule.

## Fixed candidate

Candidate id: `published_difficulty_live_2026_v1`. For a player's club, signal
is minus the mean published difficulty across that club's decision-week fixtures.
For position p, multiplier is `max(0, 1 + slope[p] * (signal - centre[p]))`.
A blank week has multiplier 1. Only the decision-week projection is adjusted;
later weeks and 3 or 5 week windows are excluded.

Use `apply_adjustment` from `src/squadopt/experiments/opponent_projection.py`
with candidate `P_published_rating`. The exact frozen values are:

| Position | Slope | Centre |
| --- | --- | --- |
| GK | 0.10084782395925615 | -2.8167342557251906 |
| DEF | 0.1711733215945405 | -2.8166785629312394 |
| MID | 0.07348818963372446 | -2.819164220126179 |
| FWD | 0.07265969217343048 | -2.8343133137337255 |

They are the last judged season's fit already recorded in
`docs/opponent_projection_study.json`. File SHA256:
`f184110399883877ab9095698f4a316982f05a90e0f3b70272d9b3eb7a31729b`.
The runner pins both values and hash and refuses a mismatch. There is no refit,
coefficient selection, new archive reading or development MSE recomputation.
The fixed function of fingerprinted pre-deadline inputs is computed at verdict
time and adds no Friday operation. The difficulty drift study stays under #998;
its result is not a condition for this protocol.

## Three readings and the gate

Join settled live total points to the captured roster by stable player code,
using the settled bootstrap's element-id-to-code map for its live payload.
One gameweek is the unit, with equal weight across scored weeks. Player counts
are reported separately and never treated as independent bootstrap units.

1. **Squared error, primary:** mean over matched players of base squared error
   minus candidate squared error, then equal-week mean. Include non-appearances
   whose settled row reports zero; do not invent zero for a missing row.
   Resample the complete paired gameweek values with replacement, 2000 draws,
   NumPy PCG64 seed 0. Report the mean and percentile interval at 0.05 and 0.95.
   The lower endpoint must be strictly greater than zero.
2. **Ordering:** use the study's within-position Spearman reading. Within a week,
   calculate each position's correlation where it has at least five matched
   players and at least two distinct predictions; omit nonfinite correlations,
   average the remaining positions, and return zero if none qualify. The
   equal-week candidate-minus-base estimate must be at least zero.
3. **Free squad:** reuse `_squad` from the same study with `OptimizationConfig()`
   as at this protocol's commit: budget 1000 tenths, squad 15, XI 11, maximum
   three per club, bench weight 0.1, expected-points scale 1000, solver wall
   ceiling 10 seconds, no deterministic-time ceiling, seed 0. Both arms use the
   same frozen squad and formation rules. Score realized starters plus the
   captain again, matching the development study's `_realized` reading. No
   transfer, hit or chip is involved. Report solver status and selected squad,
   XI and captain. If either arm cannot produce a solution, the week is missing
   for the joint gate. The equal-week candidate-minus-base estimate must be at
   least zero. This clause uses the point estimate, not an interval.

**Pass** requires all three conditions on the same population and at least
eight jointly scored weeks. Otherwise fail; fewer than eight is insufficient
evidence and cannot pass. Weekly mean absolute error and its base-minus-candidate
difference are reported as the development counterpart with no verdict. Report
the number of identical squad decisions and their zero differences.

Squared error replaces development absolute error because these forecasts are
expected values. The decision clause retains a point estimate: the development
record implies about eight points of weekly spread, giving about a 3.5 point
90 percent half-width over 14 weeks, larger than its roughly 1.74 point effect.
These already recorded development figures choose no additional live threshold.

## Missing weeks and provenance

List every week from the binding start through GW20, with a scored or missing
reason. Missing includes no targeting pre-deadline capture, an absent or ambiguous
paired handoff, a refused source or fingerprint, or no later capture that marks
the week scored and carries its settled live payload. Never repair a missing
week with another week's capture or a reconstructed post-deadline handoff.
Record excluded players and absent outcome rows rather than filling them.
The runner refuses 2025-26 in every input and cannot print a real comparison
before the settled-GW20 verdict condition. Tests use synthetic weeks only.

The verdict record is `docs/research/published_difficulty_live.md` and `.json`,
with an index row, full evidence under ignored `artifacts/`, source hashes,
code revision and working-tree state. It applies this rule unchanged.

## Shipping requires a separate decision

A pass still needs the owner's explicit yes on #1009. New version names promote
each base the weekly run can publish: `phase_c_control_components_v1` and
`phase-c-component-elite-top100-v1` unless component-only was selected. A ship
PR rebases onto any earlier DEFCON or `ep_next` promotion and names its versions.
Agree the device inputs with İbo on #981 and #984. A shipped-tree test must show
later weeks do not inherit the decision-week multiplier and device parity holds.
A failed verdict keeps this candidate parked and records that in the index.

No live, prediction, planning, optimization or scenario PR merges within 24 hours
of a deadline; no GW6 output change merges before `2026-10-10T10:00:00Z`.
No queue entry occurs while Tuesday settle or Friday publish is running.
Release to main needs the owner's yes. The owner runs weekly operations through
GW20. This protocol authorizes no publication, deployment or member-page copy.
