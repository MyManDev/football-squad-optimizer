# Explicit lookahead on a rebuilt tail

Development measurement, 30 September 2026, on one immutable GW6 capture
(`fpl-live-20260922T205533Z-7ff2c68eac7f`, captured 2026-09-22T20:55:33Z, deadline
2026-10-10T10:00Z). Runner `scripts/measure_explicit_lookahead.py`; the protocol was
written by the runner before its first solve and is in the JSON record. Constructed
squads, one supplied forecast, no realized points, no promotion.

## What is measured

`planning.lookahead.optimize_with_lookahead` (#888) solves a decision window and an
explicit tail together and separates the window's net points from the tail's. Its own
record said it was not measured, and that a five-week window had no tail because the
served forecast covers five weeks. This measurement gives it one: the served
`football_team_share_v1` pipeline (`produce_football_forecast`) rebuilt from the archive
and the capture, once for the served five weeks and once through GW19, the captured
expiry of every first-half chip right. The two rebuilds agree on GW6-10 at 1e-10 in expected points,
fixture counts and prices before any solve (the served reader carries no appearance
probability to compare; a first attempt stopped at this gate before any solve, and the
gate was narrowed to the shared columns in d9e92745). That proves the extension is
week-range-invariant on those columns, not that it equals an artifact the backend served
(none exists on this machine for this capture, and the capture is not the one the
earlier planning records used).

The producer trains on the four archive seasons it always reads, 2022-23 to 2025-26
(89,946 rows; the archive hashes are in the JSON), so this measurement reads 2025-26 as
training data, two days after the owner
[approved football development use of that season](football_defcon_development_scope.md).
It scores nothing on 2025-26. The owner's later planner studies (#906) restrict the
archive to 2022-23 to 2024-25, so their forecasts differ from this one.

Three policies are scored on that one forecast, every solve at the production rate of
twenty deterministic units per forecast week, `protect_hold=True`, linearization 2,
`TransferPlanningConfig()` defaults (a hit costs the four points it is charged), no
chips, no preferences, no Top100 weight:

- `window_then_continue`: the 3- or 5-week window solved blind to the tail, then the
  tail solved from the window's end state (squad, bank, carried free transfers). Its
  units equal the lookahead's by construction.
- `lookahead`: one solve over window and tail.
- `rolling_one_week`: fourteen sequential one-week solves with the same handoff, the
  control the earlier horizon records were measured against; its transfer counts,
  paid transfers, reversals and net points are reported apart.

Cases: two constructed squads (budget 1000 with one free transfer, 900 with none), the
served tail (window 3, tail GW9-10, what today's artifact already supports) and the
expiry tail (windows 3 and 5, tail to GW19). A tail of three weeks past the window was
declared and dropped before the run, with the chip arm: it had no declared reason and
the served tail replaces it.

## Reading rule, declared before the run

The window-then-continue path is a feasible full path for the lookahead's model, so an
exact lookahead can never be below it. A difference is therefore read only where both
control solves proved optimal; a negative difference is an unproved search shortfall and
is never written as a loss. The lookahead's objective bound gives an upper bound on the
in-forecast gain on the solver's objective, whose coefficients are rounded to 0.001
points per starter-week; on the four proved solves that bound differs from the unrounded
rescore by at most 0.0021. The declared primary finding is how often the first-week
action changed. Labels in the table: `gain_defined` (both control solves proved),
`unproved_shortfall` (a negative difference under an unproved solve), `hold_equal` (the
lookahead's first-week action is a hold, no incoming transfer), `availability_driven`. A first-week action that moves a held player the capture prices below
one is labelled availability-driven and leaves the headline, because the captured state
is held in every tail week and nobody holds that a player never returns. A solve the
wall clock stops is failed and not read; no budget was raised after a result.

## Results

Six pairs, all valid. Units are equal per pair: 100 for the served tail, 280 for the expiry tail. Every FEASIBLE solve exhausted its deterministic budget; none was stopped by the clock.

| Profile | Window | Tail | Control (window + continuation) | Lookahead | Statuses (window/continuation/lookahead) | Delta | Gain upper bound, scaled objective | Labels |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| 1000 | 3 | served to GW10 | 270.256740 | 270.608100 | OPTIMAL/OPTIMAL/FEASIBLE | +0.351360 | +2.130 | hold_equal, gain_defined |
| 1000 | 3 | expiry to GW19 | 740.122418 | 732.006587 | OPTIMAL/FEASIBLE/FEASIBLE | (-8.115832, not read) | +24.569 | unproved_shortfall, hold_equal |
| 1000 | 5 | expiry to GW19 | 740.620956 | 732.006587 | FEASIBLE/FEASIBLE/FEASIBLE | (-8.614369, not read) | +24.070 | unproved_shortfall, hold_equal |
| 900 | 3 | served to GW10 | 264.504834 | 264.753529 | OPTIMAL/OPTIMAL/FEASIBLE | +0.248695 | +0.590 | hold_equal, gain_defined |
| 900 | 3 | expiry to GW19 | 717.288527 | 713.267554 | OPTIMAL/FEASIBLE/FEASIBLE | (-4.020973, not read) | +27.623 | unproved_shortfall, hold_equal |
| 900 | 5 | expiry to GW19 | 726.497467 | 713.267554 | FEASIBLE/FEASIBLE/FEASIBLE | (-13.229913, not read) | +18.415 | unproved_shortfall, hold_equal |

Rolling one-week control on GW6-19, the same forecast and handoff, beside each squad's best expiry-tail control and its fourteen-week lookahead:

| Squad | Rolling one-week net | Solves | Transfers | Paid | Reversals | Window-then-continue, best | Lookahead, expiry tail |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1000 | 741.348265 | 14 OPTIMAL | 14 | 0 | 10 | 740.620956 | 732.006587 |
| 900 | 728.405028 | 14 OPTIMAL | 13 | 0 | 12 | 726.497467 | 713.267554 |

### Reading

**The served tail, the one arm today's served artifact could feed, reads in both squads.** With
the three-week window and the two weeks the five-week artifact already carries, both
control solves proved optimal and the lookahead returned FEASIBLE at its full hundred
units (relative gaps 0.66 percent and 0.13 percent). Its plan is worth **+0.351** (squad
1000) and **+0.249** (squad 900) more on the same forecast than window-then-continue,
with the in-forecast gain bounded above by +2.130 and +0.590. The first-week action is
the same in every arm (a hold in GW6, the first transfers in GW7) and so are the weekly
transfer counts, as the record's per-week moves show; the lookahead gives up 0.469 and 0.438 inside the window and takes
0.820 and 0.687 in the tail. That is the trade `optimize_with_lookahead` was built to
make, measured at a quarter to a third of a point over five weeks on this capture.

**The expiry tail is unsolved at the production rate, and the record says so rather
than reading it.** Every nine-, eleven- and fourteen-week solve returned FEASIBLE with
its budget exhausted and relative gaps of 3.8 to 8.2 percent. The fourteen-week
lookahead made one transfer in fourteen weeks for squad 1000 and six, five of them
reversals, for squad 900; the continuations made none or one. The hold plan's own value is not
in the record, so the margin over it is not stated; what is recorded is that a bounded
search at this rate found almost no transfer structure in fourteen weeks. The four differences (-4.0 to -13.2) are unproved shortfalls and
are not read; the upper bounds (+18 to +28) say only that nothing is proved.

**Fourteen proved one-week solves beat every fourteen-week solve on the same rescore.** The rolling one-week control reached 741.348 (squad 1000) and 728.405
(squad 900), every one of its fourteen solves proved optimal at twenty units, in about
sixteen seconds of wall clock per squad. Its path is itself a feasible fourteen-week
path, so the fourteen-week lookahead is at least 9.34 and 15.13 points below a path its
own model admits, on the independent rescore of both paths (the model's objective rounds
each starter-week coefficient to 0.001 points, so the comparison is made on the rescore). That is a measured lower bound on the search shortfall, and it is
the finding of the expiry arm: at twenty units a forecast week, the tail's value cannot
be read from one long solve, because the long solve does not reach paths the short
solves find. The rolling control also shows what a one-week policy does on a forecast
that varies by fixture: 14 and 13 transfers, none paid, of which 10 and 12 are
reversals, a player bought and sold again or sold and bought back as the fixtures
turn. In-forecast that churn
is free; what it costs in realized points is not measured here.

**First-week change: 0 of 6, the declared primary finding.** A squad constructed as the
optimum of the first week has nothing to fix in that week, so on these squads the count
is uninformative; the readings above were chosen after the run and are secondary to it.
On the expiry tail the lookahead banked free transfers toward the cap of five (3 to 5 at
the window's end, the cap reached in the two five-week windows, against 1 for the window
solve), which is the beyond-window resource the rollout named, but held unread for the
reason above.

## Limits

One capture, one forecast model, two constructed squads; not owner holdings, not the
squads of the earlier records. Captured availability held in every week: 201 of 667
players carry a multiplier below one for fourteen weeks, and squad 900 holds one of
them at zero (490145, status u, stated chance 0, a filler its budget admitted); no
first-week action moved him, so the availability label was never applied. Buy equals sell at captured prices, so purchase rebasing is inert and the opt-in
acquisition accounting (#894) stays off in every arm. The calendar is the captured one,
one fixture per club per week, no blank or double. GW19 is the first-half chip expiry,
not the season's end; banked free transfers are worth nothing at that edge in every arm.
Wall seconds are this machine's. Units are equal per comparison; equal units are not
equal difficulty, and every fourteen-week solve returned FEASIBLE. Every
number is in-forecast points on one supplied forecast; the realized negatives for longer
horizons (`planner_horizon_rolling_note.md`: rolling H3 -2.30, H4 -8.32) stand beside it.
Nothing here promotes a horizon, changes the served artifact, its reader, a default or
the prospective protocol (`football_prospective_prereg.md`), which scores the served
five-week `football_team_share_v1` and reads none of this. Injury probabilities are not
calibrated by a longer horizon; the captured state is carried, not forecast. The served
document was rebuilt with 89946 training rows, the extended one with the same
89946; both headers are in the JSON record under `forecast_documents`.

## Follow-up boundary

This record does not support lengthening the served artifact: the readable gain from
the tail the artifact already carries is a quarter to a third of a point, and the longer
tail is unsolved. What it supports is handing the long solve a path it is known to admit.
Since #901 the planner takes an optional `incumbent_plan`: the decisions are certified
against the current model in a constrained clone and then hinted, never fixed, bounded or
trusted for a score, and the input cannot be combined with `protect_hold`. Its own paired
study found no gain where the unhinted repairs already reached their restricted optima.
The case here is different in kind: a fourteen-week search that does not reach a path
fourteen one-week solves find. Handing that path to the lookahead needs
`optimize_with_lookahead` to take an incumbent in place of the hold guard. This track
proposed that seam to the planner track on #632; the handoff there reserves
`planning/optimizer.py` and `planning/refinement.py`, and `planning/lookahead.py` is not
yet named by either side. What this record carries towards it: each arm's per-week
moves, bank and carried transfers (from which every squad follows from the initial
state), the forecast document and transfer-policy fingerprints. What an incumbent must
also carry and the record does not: the planning horizon and chip availability
fingerprints, and each week's XI and captain; those are in the local results whose
sha256 the record holds, or are rebuilt from the archive hashes and the capture. Until then the expiry tail stays unread. The chip
arm was dropped because an unpriced right is spent inside any window solve; its proper
control is a reservation-priced right, which the lookahead refuses to stack, so chip
timing with transfers stays unmeasured, and a longer dated horizon is not evidence that
the automatic chip strategy is ready.

## Post-measurement changes to the record

The measured source is commit d9e92745; the protocol's source hashes are of that commit.
After the run the compaction was widened to keep each path's per-week moves in the record
and the table prints the bound column to three decimals. The `forecast_documents` block
(both rebuilt documents' headers) and the `measured_source` block were added to the
committed JSON by hand from the run's own served and extended documents, their
fingerprints cross-checked against the protocol; the runner's `compact.json` does not
carry them. No solve, input or number changed, and the local results' sha256 in the
record is unchanged.

Reproduce with `python -m scripts.measure_explicit_lookahead --snapshot-root <captures>
--archive-root <vaastav archive> --snapshot-id fpl-live-20260922T205533Z-7ff2c68eac7f
--output <fresh directory>`; the extended forecast is written into that directory and
never under a football artifact root.
