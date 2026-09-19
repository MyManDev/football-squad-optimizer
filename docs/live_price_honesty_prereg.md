# Live price honesty: protocol

Status: pre-registered on 2026-09-19, before gameweek 5 of 2026-27 kicked off. No reading under
this protocol has been taken. This document changes no plan, price, copy or live control, and
it promotes nothing.

## The claim being checked

Every choice a member can make on the page carries a price: "this choice costs X points". X is
the difference, on the week's projection, between the member's unconstrained one-week plan (the
control, `saf-puan/1`) and the plan under the choice. It is the one number the site states about
a choice, so it is the one that has to be honest.

Offline, on the development seasons, this was gate 3 of `strategy_bench`: it passed at one and
three weeks (the high-overlap tag overstated its cost by about five points) and failed for one
band at five. That was a template rival in past seasons. Nothing has read it on the live
records, where the rivals are real, the projection is the live one and the choices now include
the Top 100 weights and the manager's word.

## What is on disk, as of 2026-09-19

`member_advice_record_v2` holds, per member and capture, the control and every published
document with its decision in full. Both arms of every pair are therefore in the record and
nobody has to have followed either.

| Gameweek | Records | Documents per member | Price in the record | Realized |
| --- | --- | --- | --- | --- |
| 4 | three captures, the last 2.5 hours before the deadline | 33: the control at 1, 3 and 5 weeks, `ortak-koru` and `fark-yarat` against every rival at one week | no; it is the difference of the two recorded `expected_own_points`, net of the recorded hits | yes |
| 5 | three captures, the last 5 hours before the deadline | the same 33; the Top 100 and manager's word documents were published but recorded only since #645, which landed after that capture | the same | not yet |
| 6 onwards | one record per publish | every published document | `expected_points_cost` and its ceiling, as published | not yet |

Gameweek 4 has settled and the history page shows what each recorded plan scored. No table of
realized cost against stated cost has been computed or looked at by anyone; this protocol is
written before that table exists.

## The reading

**Unit.** One member, one setting, one gameweek, at the one-week window, from the record of the
last capture published before the deadline. Earlier captures of the same week are other advice
for the same matches and are not counted again. A setting is a rival strategy against one
rival, a Top 100 weight, the manager's word, or a recorded combination of those; a setting the
record lists twice (the default rival and the same rival chosen by name) counts once. Chips are
left out: a chip's document states a gain over not playing it, which is another claim, and a
chip spent cannot be scored against a week in which it was kept. Windows of three and five
weeks are left out: their plan is a path, and no member's later weeks follow it.

**Stated cost** `c`. From gameweek 6, the recorded `expected_points_cost`. For gameweeks 4 and
5, `expected_own_points - transfer_hit_points` of the control (the eleven with the captain
doubled, minus the week's hit) minus the same of the setting, and never below zero, because the
publication anchors the control at the best plan it holds. Both are on the base projection.

**Realized cost** `k`. `score_recorded_advice` of the control minus `score_recorded_advice` of
the setting: official automatic substitutions and captaincy, minus the recorded hit, one
function for both arms. A pair in which either arm is not `scoring_complete`, or the control
did not prove optimality, is left out and counted.

**Binding pairs only.** When a setting's plan is the control's plan, `c = k = 0` by
construction and the pair says nothing. Those pairs are counted and reported, and every mean
below is over the pairs whose decision differs from the control's.

**Statistics.** Per setting family (rival strategies, Top 100 weights, manager's word) and
pooled: the number of pairs and of binding pairs, the means of `c` and of `k`, the mean of
`k - c`, and how often `k > c`. For the stated ceiling, from gameweek 6: how often `k` exceeded
it, given as a count beside the number of pairs, with no rate claimed.

**The criterion**, the same as gate 3 offline: the price is honest if it does not understate.
It fails if the 90 percent interval of the mean of `k - c` lies entirely above zero.
Overstating is reported and is not a failure: a member told five who pays three was not
misled to their cost.

**Interval.** Members share one projection and one set of matches, and one member's settings
are nested plans, so the effective sample is the number of gameweeks. The bootstrap resamples
whole gameweeks, 2000 draws, seed fixed in the script. With fewer than six gameweeks no
interval is printed and the criterion is not evaluated.

**Declared before looking.** I expect the mean of `k - c` to be negative. The control is the
plan the projection likes best, so its expected value is inflated by selection more than any
constrained plan's, and part of every stated cost is that inflation. If that is what the
record shows, the prices are conservative and nothing needs to change.

## When it is read

- After gameweek 5 settles: a descriptive table of gameweeks 4 and 5, no interval, no verdict.
  Its purpose is to prove the instrument on real records.
- After gameweek 9 and after gameweek 15, the same dates as the live projection audit: the
  pooled reading with its interval and the criterion.

Each is a committed record with a row in `measurements_index.md`. The table regenerates after
any settled gameweek without being a new reading; only the two pooled dates carry a verdict.

## What each outcome means

- Honest or overstating: the copy stays. If the overstatement is large and stable at gameweek
  15, the owner may choose to say so on the page ("at most"), which is a copy decision and gets
  its own pull request.
- Understating, for a family: that family's price is wrong in the direction that costs a
  member points. The price formula for that family is corrected in its own pull request, with
  the correction measured offline first; until it lands the page states the ceiling for that
  family instead of the cost.

## What this protocol does not do

It solves nothing and rebuilds no advice. It reads no member's behaviour; a difference against
what the member actually scored is a separate, descriptive page and is not used here. It does
not read the three and five week windows or chips. It fits nothing.

## Reproduction

`python -m scripts.measure_live_price_honesty --season 2026-27 --through-gameweek N
--data-root <checkout>/data`, added in its own pull request before the first table, with its
arithmetic tested on synthetic records. It writes `docs/live_price_honesty.json` and `.md`.
