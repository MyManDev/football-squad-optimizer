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
expiry of every first-half chip right. The two rebuilds agree on GW6-10 at 1e-10 before
any solve; that proves the extension is week-range-invariant, not that it equals an
artifact the backend served (none exists on this machine for this capture, and the
capture is not the one the earlier planning records used).

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
expiry tail (windows 3 and 5, tail to GW19).

## Reading rule, declared before the run

The window-then-continue path is a feasible full path for the lookahead's model, so an
exact lookahead can never be below it. A difference is therefore read only where both
control solves proved optimal; a negative difference is an unproved search shortfall and
is never written as a loss. The lookahead's objective bound gives an upper bound on the
in-forecast gain. A first-week action that moves a held player the capture prices below
one is labelled availability-driven and leaves the headline, because the captured state
is held in every tail week and nobody holds that a player never returns. A solve the
wall clock stops is failed and not read; no budget was raised after a result.

## Results

Six pairs, all valid. Units are equal per pair: 100 for the served tail, 280 for the expiry tail. Every FEASIBLE solve exhausted its deterministic budget; none was stopped by the clock.

| Profile | Window | Tail | Control (window + continuation) | Lookahead | Statuses (window/continuation/lookahead) | Delta | Gain upper bound | Labels |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| 1000 | 3 | served to GW10 | 270.256740 | 270.608100 | OPTIMAL/OPTIMAL/FEASIBLE | +0.351360 | +2.130260 | hold_equal, gain_defined |
| 1000 | 3 | expiry to GW19 | 740.122418 | 732.006587 | OPTIMAL/FEASIBLE/FEASIBLE | (-8.115832, not read) | +24.568582 | unproved_shortfall, hold_equal |
| 1000 | 5 | expiry to GW19 | 740.620956 | 732.006587 | FEASIBLE/FEASIBLE/FEASIBLE | (-8.614369, not read) | +24.070044 | unproved_shortfall, hold_equal |
| 900 | 3 | served to GW10 | 264.504834 | 264.753529 | OPTIMAL/OPTIMAL/FEASIBLE | +0.248695 | +0.590166 | hold_equal, gain_defined |
| 900 | 3 | expiry to GW19 | 717.288527 | 713.267554 | OPTIMAL/FEASIBLE/FEASIBLE | (-4.020973, not read) | +27.623473 | unproved_shortfall, hold_equal |
| 900 | 5 | expiry to GW19 | 726.497467 | 713.267554 | FEASIBLE/FEASIBLE/FEASIBLE | (-13.229913, not read) | +18.414533 | unproved_shortfall, hold_equal |

Rolling one-week control on GW6-19, the same forecast and handoff, beside each squad's best expiry-tail control and its fourteen-week lookahead:

| Squad | Rolling one-week net | Solves | Transfers | Paid | Reversals | Window-then-continue, best | Lookahead, expiry tail |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1000 | 741.348265 | 14 OPTIMAL | 14 | 0 | 10 | 740.620956 | 732.006587 |
| 900 | 728.405028 | 14 OPTIMAL | 13 | 0 | 12 | 726.497467 | 713.267554 |

### Reading

**The served tail, the one arm the product could use today, reads in both squads.** With
the three-week window and the two weeks the five-week artifact already carries, both
control solves proved optimal and the lookahead returned FEASIBLE at its full hundred
units (relative gaps 0.66 percent and 0.13 percent). Its plan is worth **+0.351** (squad
1000) and **+0.249** (squad 900) more on the same forecast than window-then-continue,
with the in-forecast gain bounded above by +2.130 and +0.590. The first-week action is
the same in every arm (a hold in GW6, the first transfers in GW7) and so are the weekly
transfer counts; the lookahead gives up 0.469 and 0.438 inside the window and takes
0.820 and 0.687 in the tail. That is the trade `optimize_with_lookahead` was built to
make, measured at a quarter to a third of a point over five weeks on this capture.

**The expiry tail is unsolved at the production rate, and the record says so rather
than reading it.** Every nine-, eleven- and fourteen-week solve returned FEASIBLE with
its budget exhausted and relative gaps of 3.8 to 8.2 percent. The fourteen-week
lookahead made one transfer in fourteen weeks for squad 1000 and six, five of them
reversals, for squad 900; the continuations made none or one. These plans sit a little
above the protected hold, which is what a bounded search returns when it cannot find
the transfer structure. The four differences (-4.0 to -13.2) are unproved shortfalls and
are not read; the upper bounds (+18 to +28) say only that nothing is proved.

**Fourteen proved one-week solves beat every fourteen-week solve on the model's own
objective.** The rolling one-week control reached 741.348 (squad 1000) and 728.405
(squad 900), every one of its fourteen solves proved optimal at twenty units, in about
sixteen seconds of wall clock per squad. Its path is itself a feasible fourteen-week
path, so the fourteen-week lookahead is at least 9.342 and 15.137 points below a path
its own model admits. That is a measured lower bound on the search shortfall, and it is
the finding of the expiry arm: at twenty units a forecast week, the tail's value cannot
be read from one long solve, because the long solve does not reach paths the short
solves find. The rolling control also shows what a one-week policy does on a forecast
that varies by fixture: 14 and 13 transfers, none paid, of which 10 and 12 are
reversals, a player sold and bought back as the fixtures turn. In-forecast that churn
is free; what it costs in realized points is not measured here.

**First-week change: 0 of 6.** A squad constructed as the optimum of the first week has
nothing to fix in that week, so the count the observed rollout reports is uninformative
on these squads and is not the headline; the resource path is. On the expiry tail the
lookahead banked free transfers to the cap (3 to 5 at the window's end against 1 for
the window solve), which is the beyond-window resource the rollout named, but held
unread for the reason above.

## Limits

One capture, one forecast model, two constructed squads that hold no player priced at
zero; not owner holdings, not the squads of the earlier records. Captured availability
held in every week: 201 of 667 players carry a multiplier below one for fourteen
weeks, and squad 900 holds one of them (490145); no first-week action moved him, so
the availability label was never applied. Buy equals sell at captured prices, so purchase rebasing is inert and the opt-in
acquisition accounting (#894) stays off in every arm. The calendar is the captured one,
one fixture per club per week, no blank or double. GW19 is the first-half chip expiry,
not the season's end; banked free transfers are worth nothing at that edge in every arm.
Wall seconds are this machine's. Units are equal per comparison; equal units are not
equal difficulty, and the fourteen-week solves were expected to return FEASIBLE. Every
number is in-forecast points on one supplied forecast; the realized negatives for longer
horizons (`planner_horizon_rolling_note.md`: rolling H3 -2.30, H4 -8.32) stand beside it.
Nothing here promotes a horizon, changes the served artifact, its reader, a default or
the prospective protocol.

## Follow-up boundary

This record does not support lengthening the served artifact: the readable gain from
the tail the artifact already carries is a quarter to a third of a point, and the longer
tail is unsolved. What it supports is the experiment the triple-repair record named in
its follow-up boundary, carrying a known incumbent into the solve as a hint. The hold
guard already does this for the hold plan (a verified plan, a lower bound on the
objective, a warm start); the same mechanism could take the rolling path or the
window-then-continue path, after which a long lookahead is at least the best known path
by construction and its difference is a menu-inclusion magnitude, readable even when
FEASIBLE. That is a `planning/` change, separately declared, outside the freeze window.
The chip arm was dropped because an unpriced right is spent inside any window solve;
its proper control is a reservation-priced right, which the lookahead refuses to stack,
so chip timing with transfers stays unmeasured.

Reproduce with `python -m scripts.measure_explicit_lookahead --snapshot-root <captures>
--archive-root <vaastav archive> --snapshot-id fpl-live-20260922T205533Z-7ff2c68eac7f
--output <fresh directory>`; the extended forecast is written into that directory and
never under a football artifact root.
