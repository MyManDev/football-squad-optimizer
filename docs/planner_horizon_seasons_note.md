# Reading the multi-season planner horizon measurement

Companion to [planner_horizon_seasons.md](planner_horizon_seasons.md) (contract
`planner_horizon_seasons_v1`), which is the mechanical output of
`scripts.run_planner_horizon_seasons`. This note says what the numbers mean for the
question the prediction side handed over: the projection drifts only ~2.6% per gameweek
of horizon (`horizon_decay`), so where does the H4 planner loss come from?

## The single-season screen did not generalise

`planner_doe` measured 2024-25 alone, six windows: H2 +4.83, H3 +1.17, H4 -3.67. On the
same six start gameweeks over all four development seasons (23 windows; 2022-23 GW5 is
dropped for every horizon because GW7 was postponed and the four-week window does not
fit):

| Horizon | Windows | Mean advantage | SE | Positive share | Selection | Hit disadvantage |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 23 | -0.57 | 1.7 | 0.30 | -1.43 | -0.87 |
| 3 | 23 | +1.00 | 3.2 | 0.57 | -0.74 | -1.74 |
| 4 | 23 | -4.87 | 3.4 | 0.30 | -6.43 | -1.57 |

- **H2's +4.83 was 2024-25.** Its four-season mean is -0.57, and its per-season means
  run -5.67 / -3.00 / +1.17 / +4.83. Nothing about horizon two is a live knob.
- **No horizon beats the myopic baseline beyond noise.** The standard errors are 1.7 to
  3.4 points against means of -0.6 to +1.0 for H2 and H3; per-window swings run from -36
  to +31. H4's -4.87 is the only mean that is more than one standard error from zero,
  and it is about 1.4 of them.
- **H4 loses on selection, not on hits.** Its selection term (realized points of the
  planned squads minus the myopic squads, before hits) is -6.43; its hit term actually
  *helps* it, because the planner pays fewer hits than the myopic baseline in every
  horizon (H4: 2.26 vs 3.83 points per window). A four-week plan amortises transfers;
  the weekly baseline pays for reacting. That is the opposite of the "long horizon takes
  hits for far doubles" hypothesis.

## Where the selection loss lives: windows with no calendar structure

Under `naive_calendar_scaling_v1` the only thing that makes one week's projection differ
from the next is the fixture calendar — a double or blank ahead. So windows split
cleanly into two kinds. In *calendar-structured* windows the plan and the weekly choice
can legitimately differ; in *plain* windows they differ only because the plan was made
once at the start while the baseline re-projects every week with fresher form.

| Horizon | Structured windows | Advantage | Selection | Plain windows | Advantage | Selection |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 5 | -2.00 | -6.00 | 18 | -0.17 | -0.17 |
| 3 | 12 | +0.50 | -2.83 | 11 | +1.55 | +1.55 |
| 4 | 13 | -1.23 | -3.69 | 10 | **-9.60** | **-10.00** |

H4's loss concentrates in the **plain** windows — the ones with no calendar reason to
plan at all — and there it is entirely selection. Where the calendar does carry
structure, H4 is roughly level with the baseline.

## What that says about the cause

The full-roster projection is nearly as accurate three weeks out as it is today
(`horizon_decay`: MAE +7.8% over three gameweeks). But a plan is not made from the full
roster; it is made from the top of the ranking, and the top of the ranking is exactly
where the selection-optimism profile (`selection_optimism`: -2.96 points per selected
starter, uniform across positions) says the projection is most wrong. Fresh weekly
re-projection lets the myopic baseline re-rank as recent form regresses; a four-week
plan commits to the week-one ranking and rides that regression. So the honest reading
is: **the H4 loss is information staleness acting at the top of the ranking, which
roster-level MAE decay understates by construction — not calendar handling, not hit
policy, and not a planner defect in the sense of a wrong constraint or objective.** The
prediction side's pointer ("look inside the planner") lands on the interface between the
two: how much a plan should trust a ranking it will not get to revise.

Two things follow, neither done here:

- The rehearsal's fairness frame is asymmetric on information: the baseline re-projects
  weekly, the plan never does. A rolling-horizon rehearsal (re-plan every week with the
  same horizon, keeping the state) is the comparison a live planner would actually face,
  and it is the next measurement before any horizon-policy search.
- Decision-side projection shrinkage (`position_mean_shrinkage_v1`) was built for
  exactly the top-of-ranking optimism above and is order-preserving within a week; its
  effect *across* weeks in a plan is unmeasured and is a cheap next experiment.

## Limits

**The measurement is recommendation-quality, not byte-reproducible.** The rehearsal's
planner solves stop at the frozen 10-second wall-clock cap with no deterministic work
budget, and the H3/H4 planning models do not always prove optimality inside it. Two
identical runs of this script on this machine moved the H3 mean from +0.74 to +1.00 and
the H4 mean from -4.57 to -4.87 (H2 and every plain-window figure were identical); the
committed artifact is the second run. Those shifts are a tenth of the standard errors
and change no reading above, but a formal horizon comparison would need the
deterministic-budget stopping rule the scenario objective already uses.

23 windows per horizon is small; the per-season table shows sign flips in every horizon.
`naive_calendar_scaling_v1` is a rehearsal projection rule, not the prediction side's
horizon builder (`live/horizon.py`), so a real multi-gameweek projection may move these
numbers. Nothing here promotes or demotes a horizon; the operational path remains
single-gameweek.
