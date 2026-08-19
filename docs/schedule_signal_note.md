# What the schedule signal study settles, and what it does not

`schedule_signal_study.md` is the first stage of the recommender programme, and it returned
a split answer. This note says which half is evidence for what, because the two halves point
in opposite directions and quoting either one alone would misdescribe the result.

## The calendar pays; the difficulty inside it did not

Over 4,403 paired five-week windows in 2022-23, 2023-24 and 2024-25:

- **`B_calendar` against `A_flat`** — knowing how many fixtures the window actually holds,
  against repeating a player's recent rate five times — improves mean absolute error by
  **+0.114 points** with a 90% interval of **[+0.078, +0.151]**, the sign holds in all three
  seasons, the within-position ordering improves by +0.034, and the squad built from it is
  worth **+14.7 realized points per window**. That gate **passes** — though its own
  transfer check lands at exactly **0.0 net** over ten proposed moves, clearing the
  declared “not negative” bar with no margin at all. It is the same effect
  the season chain measured from the other direction: a calendar-blind control loses about
  58 net points a season.
- **`C_published_difficulty` against `B_calendar`** — scaling each fixture by the platform's
  own difficulty rating — improves error by **+0.026** with an interval of **[+0.007,
  +0.044]**. The interval clears zero, so the signal is real. But the sign reverses in
  2022-23 (−0.036), the ordering barely moves (+0.004), and at the decision level the squad
  it builds is **−2.6 points per window** worse and the transfers it proposes lose **−8.5
  points net** across ten moves. That gate **fails**.
- **`D_carried_strength` against `B_calendar`** — the same shape, with difficulty taken from
  a club-strength proxy computed from completed gameweeks and split by the side of the ball
  the position is paid for — does not even clear the accuracy bar (**−0.006**, interval
  **[−0.028, +0.014]**), and its decision check is also negative.

## Reading it honestly

The failure is not "opponent difficulty does not matter". Three things are true at once:

1. **The signal exists and is small.** A statistically clear +0.026 points of error on a
   five-week window is roughly a third of one percent of the window's mean outcome. The
   residual scan found the same order of magnitude from the other side (+0.162 attacking,
   +0.322 defensive residual spread per gameweek).
2. **Most of it is already priced in.** The rate a player carries into the window was earned
   against real opponents, and strong clubs' players carry higher rates. Scaling that rate
   by difficulty double-counts part of what it already contains, which is the most likely
   reason the accuracy gain does not survive to the decision.
3. **The instruments used here are blunt.** The published rating is opaque and constant
   across a season; the carried proxy is fantasy points per club per week, normalised inside
   the origin. Neither is a model of goals, neither separates attack from defence properly,
   and neither says anything about a clean sheet — which is where the defensive half of the
   squad is actually paid.

## What this changes about stages S1 and S2

It changes their status, not their existence. Before this run, an opponent-aware projection
was the obvious next build. After it, the bar is explicit and higher:

- A team rating (**S1**) has to beat the published difficulty rating on its own ground —
  out-of-sample goal likelihood and clean-sheet calibration — before it earns the right to
  touch a projection. If it cannot beat an opaque five-point scale at predicting goals, it
  is not the instrument that changes the answer above.
- An opponent-aware projection (**S2**) has to be judged **at the decision level**, not on
  error alone. This study is the proof that the two can disagree: the published rule
  improved error and lost points. Any S2 result that reports only an error improvement is
  reporting the half that does not decide anything.
- The multiplicative shape used here — rate times ease — is itself a suspect. A clean sheet
  is a probability, not a scale factor, and a defender's points are a step function of it.
  S2 uses the probability directly for goalkeepers and defenders rather than a fitted
  multiplier, and that difference is one of the things being measured.

## Limits of this study

- **Eighteen windows** carry the decision check per comparison, six per season, chosen not to
  overlap so the paired interval is not inflated by shared gameweeks. That is a small sample
  with a wide spread (−28 to +14 points), and the accuracy comparison, at 4,403 rows, is far
  better resolved than the decision comparison.
- The transfer check prices the two players swapped over the window. It does not re-pick the
  eleven or the captain week by week, so it measures the ordering the rule imposes rather
  than a season of play.
- Squads are rebuilt from scratch at each origin under the full budget, which is not how a
  mid-season manager holds a team; it is applied identically to every rule, so it compares
  rules fairly without describing a real season.
- Windows open at gameweeks 6, 11, 16, 21, 26 and 31, so the opening of a season — where
  form is thinnest and difficulty should matter most — is not represented here at all.
