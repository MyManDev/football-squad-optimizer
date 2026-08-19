# Reading the rolling-horizon planner measurement

Companion to [planner_horizon_rolling.md](planner_horizon_rolling.md) (contract
`planner_horizon_seasons_v1`, `rolling_replan: true`), the mechanical output of
`scripts.run_planner_horizon_seasons --rolling --start-gameweeks every:2
--deterministic-time-limit 8`. It answers the question the four-season measurement
([planner_horizon_seasons_note.md](planner_horizon_seasons_note.md)) left open: the
one-shot H4 plan lost on selection in windows where its only handicap was information
staleness — so does a planner that **re-plans every week** with fresh projections, applying
only the first week's decision, recover the loss?

## Design

- Four development seasons, starts every second gameweek from GW2 to GW34 → **66 windows
  per horizon**, shared across horizons (ten starts dropped where the four-week window did
  not fit; 2022-23 GW7 was postponed and is not a decision point).
- Three strategies per window on identical pools and opening squads: the **myopic** weekly
  baseline (lookahead one), the **one-shot** plan (made at the start, followed to the end),
  and the **rolling** planner (lookahead H every week, first decision applied, state
  carried; the lookahead ends at a gameweek the season never played).
- Deterministic solver budget 8.0 with the wall clock raised to 60 s, so the budget binds
  and the run is reproducible. Every solve records its status and relative gap.
- Season-aware moving-block bootstrap intervals (90%) on the per-window advantages.

## The numbers

Advantage = strategy net points minus myopic net points over the window.

| Horizon | One-shot mean [90% CI] | Rolling mean [90% CI] | Rolling positive share |
| ---: | --- | --- | ---: |
| 2 | -0.68 [-1.98, +1.29] | -0.94 [-1.92, +0.35] | 0.12 |
| 3 | +0.32 [-2.18, +2.83] | **-2.30 [-4.15, -0.39]** | 0.24 |
| 4 | **-5.15 [-7.03, -0.91]** | **-8.32 [-11.12, -6.30]** | 0.20 |

Decomposed into selection (realized points before hits) and hits, per window:

| Horizon | One-shot selection | One-shot hits | Myopic hits | Rolling selection | Rolling hits | Rolling transfers |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | -0.86 | 1.15 | 1.33 | -0.15 | 2.12 | 2.5 |
| 3 | -1.56 | 1.58 | 3.45 | +1.33 | 7.09 | 4.7 |
| 4 | -7.94 | 3.03 | 5.82 | +0.35 | 14.48 | 7.6 |

## What it says

1. **Re-planning removes the selection loss — and replaces it with a hit bill.** The
   one-shot H4 plan lost 7.94 points per window on selection; the rolling H4 planner's
   selection is level with myopic (+0.35). So the staleness reading was right: a plan that
   sees fresh projections picks as well as the weekly baseline. But the rolling planner
   pays **14.5 hit points per four-week window** — 3.6 paid transfers a week — against
   5.8 for myopic and 3.0 for the one-shot plan, and the advantage ends at -8.32 with the
   whole interval below zero.
2. **The churn is structural under naive calendar scaling.** Each week's fresh horizon
   reveals a new far week whose only difference from today is its fixture count; a double
   two or three weeks out looks worth a transfer now, the transfer is made, and next week
   the horizon shifts and reveals another. The one-shot plan sees each double once and
   buys it once; the myopic planner never sees it and never buys it; the rolling planner
   sees it again every week from a different distance and keeps buying. Hit cost 4 does not
   deter a projected double, because a doubled projection clears 4 easily on paper and
   the realized double does not — the same top-of-ranking optimism the selection-optimism
   profile measured, now applied to fixture-scaled projections.
3. **No horizon beats the weekly baseline in either mode.** One-shot H3 (+0.32) and H2
   (-0.68) are noise; rolling H2 is noise; rolling H3 and both H4 modes are significantly
   negative. Under `naive_calendar_scaling_v1`, deciding one week at a time with one free
   transfer is the dominant policy in this frame.

## What it does not say

- It does not condemn look-ahead planning; it condemns look-ahead planning **on
  projections whose only inter-week signal is the fixture count, with no control on paid
  transfers.** Two things would change the frame and are the next measurements, in order:
  - a **transfer discipline** in the rolling planner — a cap on paid transfers per week or
    per horizon, or a hit cost applied at the horizon's projected optimism rather than at
    face value; the discount factor the one-shot screen found dead is a candidate again
    here, because rolling churn is exactly what discounting far weeks would damp;
  - **chips**. In the real game a double is bought with a bench boost or a triple captain,
    not with three -4 transfers. A planner without chips has only hits with which to chase
    a double, which is the behaviour above. Chip modelling (first with hand-timed chips) is
    the honest way to give the horizon something to plan *with*.
- Solve quality is uneven with horizon: proven-week share 0.98 / 0.67 / 0.42 for rolling
  H2 / H3 / H4, mean relative gap on unproven weeks 0.2% / 2.6% / 4.5%; one-shot proven
  share 1.00 / 0.77 / 0.53. Multi-week horizons that cross a double are hard for the
  current CP-SAT formulation inside an 8-unit deterministic budget. The rolling H4 figure is
  therefore a handicapped lower bound — but the mechanism (hits) is visible in the fully
  proven H2 rows too, and a better-solved H4 would buy *more* doubles, not fewer.
- Season means still flip sign for H2 and H3 (per-season table in the artifact); 66
  windows is three times the previous sample, not a large one.

## Operational reading

The live path stays single-gameweek: one free transfer, weekly decision, no horizon.
Nothing here promotes or demotes a control. The multi-week planner is not ready for the
live path, and the reason is now specific enough to act on — churn control and chips —
rather than "loses on average".
