# Available attacking shares: 2026-27 prospective protocol

Issue #1009 part (a), step 2. The forecast-only sizing step in PR #1032 meets
the unchanged go rule: four available players gain at least 0.2 expected points
on its declared GW6 capture. This protocol is conditional on that sizing record
being accepted and merged. Sizing is not an outcome or an accuracy finding.
No prospective outcome is read before this protocol merges.

## Arms and binding start

The base is `football_joint_role_retained_history_v1`. The candidate is
`football_retained_history_available_shares_v1`, built with the same retained
history and training selection. Only the goal and assist split changes.
For each channel and club-fixture, the conditional share for player i is
`w_i / (w_i + sum(j != i, m_j * w_j))`, using existing weights and captured
availability m. The reader applies m_i exactly once. All other components stay
the same. The candidate has its own artifact root and is never substituted for
the base, v1 or v1's shadow. Their fingerprints and bytes remain unchanged.

The owner clarification on #1009 governs the all-absent or zero-positive-weight
boundary before candidate code can be approved. This protocol neither supplies
that decision nor changes its primary reading. The candidate PR also cites the
merged retained-history base record from #997 and needs Ibo's approving review.

The first scored week is the first 2026-27 deadline strictly after both this
protocol and the candidate implementation merge. Candidate artifacts must exist
before their own deadlines. The record names both merge commits and times and
the resulting first week; no earlier week enters the prospective reading.
The population ends at GW20, deadline `2027-01-05T18:00:00Z`.

## Captures, timely artifacts and outcomes

For each eligible week g, the scored capture is the decision capture: the last
`fpl-live` capture, by capture instant, whose own target is g
(`read_inputs(snapshot, season="2026-27").deadline.gameweek` in
`src/squadopt/live/recommendation.py`) and for which the weekly run's handoff
root holds a served baseline handoff (`handoff_fingerprint_for` in
`src/squadopt/platform/capture_context.py`). A capture without one was never
served; it is passed over and listed as unserved, so a later audit capture does
not displace the served one. Two captures at the same latest instant make the
week missing. A later own-target capture given its own baseline handoff before
the deadline becomes the decision capture and needs its own base and candidate
artifacts before the deadline, or the week is missing.

Base and candidate artifacts must carry equal `source_snapshot_id`,
`source_fingerprint`, `captured_at_utc`, `season`, `gameweek`,
`training_latest_kickoff` and `training_selection`, naming the decision capture
and its own target. Read each with the existing validated forecast and
fixture-component contracts. Record versions, fingerprints, input hashes,
artifact hashes and filesystem modification instants.

An artifact with file time at or after the deadline is missing. Never rebuild a
prospective candidate after the deadline or fill a missing week with another
capture. The owner runs the added shadow build on the decision capture before
each deadline, under a separate runbook PR. This protocol does not run weekly
operations or publish.

Use the first later capture whose recorded calendar marks the scored gameweek
finished and data_checked and whose live payload covers it. Realized attacking
points come from that live payload's per-fixture explanations: goal points by
captured position plus three per assist. Join its element ids through the settled
bootstrap's stable player codes, then match the pre-deadline fixture id. For
doubles, score the separate fixture explanations; do not split a weekly total.
No goals or assists column is added to the settled-outcomes feature table.

A player's realized goals and assists in a fixture are the `value` of the
`goals_scored` and `assists` items in his `explain` entry for that fixture id.
An item absent from that entry counts as 0, and so does a fixture for which he
has no entry. A row is ambiguous when any of his entries names a fixture outside
his captured club's fixtures in that gameweek, or when his goals or assists
summed over his entries differ from his weekly `stats.goals_scored` or
`stats.assists`. Ambiguous rows are excluded and counted. A player whose element
is absent from the settled payload, and a pre-deadline fixture that the settled
capture no longer places in the gameweek, are excluded and counted, never scored
as zero.

## Primary reading and pass rule

Population: decision-week player-fixtures at club-fixtures where at least one
rostered player has captured m < 1, counting only players with m > 0.
Eligibility is fixed from the decision capture and companion, before outcomes.
Include both partial and fully available players. A player's absence after the
capture does not retrospectively change eligibility.

Predicted attacking points are `(goal_points[position] * goals + 3 * assists)
* m`, separately for each arm and fixture. For 2026-27, goal points are GK 10,
DEF 6, MID 5 and FWD 4. Availability is applied once. Realized attacking points
are the settled fixture's scored goals and assists under those same values.

For each eligible fixture row, calculate base squared error minus candidate
squared error. Average within each gameweek, then equally across scored weeks.
Players within a week share a club forecast and fixtures, so the gameweek is the
bootstrap block: resample whole paired gameweeks with replacement, 2000 draws,
NumPy PCG64 seed 0, percentile endpoints 0.05 and 0.95.

There is one verdict after every GW20 fixture has settled. The record names
the earliest capture demonstrating GW20 finished and data_checked. Pass requires
at least eight scored weeks and the entire primary 90 percent interval strictly
above zero. Otherwise fail; fewer than eight is insufficient evidence and cannot
pass. A week with no eligible observed rows is listed as missing, not zero.
No outcome of a scored week is read for any reading of this protocol, primary or
secondary, before a capture shows GW20 finished and data_checked. Until then a
runner may check inputs only (captures, artifacts, write times, bindings and
missing reasons) and refuses any real-week comparison. Each reading is taken
once, at the verdict, and no verdict is repeated.

Squared error is the primary loss because most realized attacking points are
zero and absolute error would reward the very downward shrinkage being tested.
The rule is not changed after data is read.

## Secondary readings, with no verdict

- The same attacking squared-error comparison across all matched players,
  including those with m = 0 and club-fixtures without absentees.
- Total-points squared error on all matched decision-week player rows, using the
  two full forecasts after availability and settled weekly total points.
- One free squad per arm per week, following reading one of
  `docs/football_prospective_prereg.md`: budget 1000 tenths, Top100 weight zero,
  manager word off, no transfer, hit or chip, identical optimization rules;
  linearization level 2, one worker, seed 0, wall ceiling 1800 seconds,
  deterministic budget 60 then 240 if unproven. Complete and score the frozen
  decision with official normal-week substitutions and captain fallback. Omit
  and count weeks where either arm's primary or tie-break remains unproven at
  the larger budget. Report paired realized difference and identical decisions.
- Club attacking totals, for each arm and each channel. For a club-fixture,
  credited goals are the sum over the players the forecast lists for it,
  including those with m = 0, of m times the arm's forecast goals; credited
  assists likewise. Realized goals and assists are the sums of the same players'
  realized values read as above, so own goals do not count. Report the
  equal-week mean of realized minus credited and of its square, over all
  club-fixtures and over eligible club-fixtures alone, preserving fixture ids.
  A club-fixture with an excluded row is left out and counted.

These explain the primary finding; none is an extra pass condition. Report counts
and equal-week means, and retain full rows under ignored `artifacts/`.

## Missing weeks and verdict record

Apply the missing-week rules in `docs/football_prospective_prereg.md`, with this
protocol's two named football versions: list every week from the binding start
through GW20; no decision capture (no own-target capture, none with a served
baseline handoff, or two at the latest instant), missing or late required
artifact, invalid binding or model version, or missing settled live payload is
recorded with its reason. Secondary
missingness is reported separately and cannot remove a valid primary week.
A late artifact may be labelled replay beside the record and never pooled.
The locked 2025-26 holdout remains unopened.

The later scoring runner and verdict PR add a small markdown and JSON record
under `docs/research/` and a `docs/measurements_index.md` row. Record source and
code provenance, every scored week's timely candidate artifact, missing reasons,
the frozen readings and the single verdict. Do not claim a shipping result from
the forecast-only sizing.

## Separate implementation and shipping gates

The candidate PR waits until after the GW6 publish boundary
`2026-10-10T10:00:00Z`. It proves all-available equality, the owner-approved
binary boundary rule, shares in [0, 1], unchanged fixed-capture v1 and base
fingerprints, and no backend share-limit sentence for the new version. It records
build wall time on the owner's PC, then waits for Ibo's approving review.
No frozen-path PR merges within 24 hours of a deadline, and no queue entry occurs
while a weekly run is underway. The owner runs Tuesday and Friday through GW20.

A pass still needs the owner's explicit yes on #1009 and a surviving football
option under #988. A separate ship PR selects the new version at the first
deadline after merge and names what #844 and
`docs/research/planner_policy_chain_prereg.md` score after that switch. A failed
verdict leaves the served version unchanged and records the result. If the owner
drops the football option, that decision is recorded on the issue instead.
This protocol authorizes no member-page text, release or backend operation.
