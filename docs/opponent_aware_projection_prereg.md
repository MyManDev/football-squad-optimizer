# Opponent-aware projection: evaluation protocol

Status: pre-registered; no measurement under this protocol has run. This document changes no
arm, gate, projection or live control.

It freezes **what will be read** about one candidate, before any number is read: a projection
that knows who a player's club plays and where, built only from results that were final before
the decision. It names the candidate, the arms, the population, the readings, the comparator
that decides each gate, and the falsifiers.

## Why this candidate, and what it is not

Three facts from the repository's own records set the question.

1. **The later weeks of a member's three or five week plan are the first week's numbers.**
   `live/horizon.py` scales each later week by the club's fixture count relative to the first
   week (`first_week_control_relative_fixture_scaling_v3`). Doubles and blanks are therefore in
   the plans already. The opponent and the venue are not: `home_fixture_count` is carried and
   never enters the arithmetic.
2. **The one-week projection does not know the opponent either.** The component model's only
   next-fixture inputs are `fixture_count` and `home_fixture_count`
   (`prediction/component_dataset.py`, `PRE_MATCH_FEATURE_COLUMNS`). The archive's difficulty
   integer is omitted on purpose: it shares a row with the final score and cannot prove a
   pre-deadline instant (`features/fixtures.py`).
3. **Planning ahead under such a projection has been measured, and it loses.** Rolling H = 3
   loses 2.30 points a window to the weekly decision and H = 4 loses 8.32
   (`planner_horizon_rolling`); the projection's error grows about 2.6 per cent of MAE a week
   (`horizon_decay`, under an older scaling rule).

The figure of about 58 net points a season (`season_chain_blind`) is **not** a target here. It
is the value of knowing the fixture *count* to the weekly control, and the product has it.

This protocol is not a promotion. Nothing it licenses changes the operational control, which
moves only through `PromotionPolicy` and a frozen holdout. It is not a claim about the live
2026-27 season. And it does not reopen the archive's difficulty integer.

## The candidate: `opponent_venue_v1`

Everything below is computed, for a decision at gameweek *g* of season *s*, from matches of
gameweeks before *g* in season *s* and from completed earlier seasons. Nothing from gameweek *g*
or later is read, and the locked 2025-26 season is named to no loader.

**Team match scores** are taken from the player panel, because the fixture panel carries no
score: a club's goals conceded in a fixture is the maximum `goals_conceded` over that club's
players in that fixture, and its goals scored is its opponent's goals conceded.

**Ratings.** For each club, an attack rate (goals scored per match) and a defence rate (goals
conceded per match), each an exponentially weighted mean over the club's matches in time order
with a half-life of 19 matches. A club enters a season with its rates at the end of the previous
season. A club with no previous top-flight season in the panel enters with the mean of the rates
the three clubs relegated before that season held at its end. The league mean rate *m* is the
mean goals per club per match over the same information.

**Venue.** One league-wide home factor *H*: home goals per match divided by away goals per
match, over the completed earlier seasons only. A home fixture multiplies a club's expected
goals by the square root of *H*; an away fixture divides by it.

**Expected goals of a fixture.** For club *t* against opponent *o*:
`lambda_t = attack_t * defence_o / m * venue_t`, and the same for the opponent.

**Fixture factors.** Attacking factor `f_att = lambda_t / m`. Defensive factor
`f_def = exp(-lambda_o) / exp(-m)`, the ratio of a clean sheet's Poisson chance in this fixture
to its chance in an average one.

**Position shares.** For each position, the share of points that came from appearance
(minutes points), from attacking returns (goals, assists, and the bonus on those matches is
left with them) and from defensive returns (clean sheets, goals conceded, saves, defensive
contribution), measured on completed earlier seasons only. Shares sum to one by position.

**The multiplier.** For one fixture: `s_app + s_att * f_att + s_def * f_def`. For a gameweek, a
player's projected points are the control's per-fixture points times the sum of the multipliers
of that gameweek's fixtures. With every factor at one this is the control, which is the
candidate's own sanity check and is tested.

**Frozen parameters:** half-life 19 matches; one league-wide home factor; Poisson clean sheets;
three shares per position. They are not tuned on the readings below. A changed parameter is a
new candidate with its own protocol.

## Compared arms

| Arm | Later weeks and the first week |
| --- | --- |
| `control` | `naive_calendar_scaling_v1`: the historical Ridge projection times the fixture count, as every horizon record in this repository was measured |
| `opponent_venue_v1` | the same projection times the sum of the fixture multipliers above |

Both arms read the same panel, the same folds, the same calendar and the same solver limits.
The calendar is the archive's, which is hindsight about postponements for both arms alike; that
is a stated limit and not a difference between the arms.

## Population

The development seasons 2021-22, 2022-23, 2023-24 and 2024-25, every decision gameweek with at
least one prior gameweek in its season, as `build_walk_forward_folds` builds them (147
decisions). 2020-21 is read as history only. 2025-26 is not read.

## Readings

**R1, accuracy.** For offsets 0 to 4 (the decision week and the four after it), per player and
gameweek with positive control projection: mean absolute error, bias, and the Spearman rank
agreement within gameweek and position. Reported for all players, and separately for the
players inside each position's top 40 by control projection, because that is where the solver
buys.

**R2, the weekly decision.** One squad per arm walked through each season by the weekly
decision (lookahead 1) on the season chain, hits paid, no chips. Net points per decision
gameweek, paired across arms.

**R3, planning ahead.** Under the candidate only: the rolling three-week planner (re-plan every
week, execute the first week) against the weekly decision, paired per decision gameweek. This
is the record `planner_horizon_rolling` read under the control, read again under the candidate.

Every paired reading carries a 90 per cent season-aware moving-block bootstrap interval, block
length 4, 5000 resamples, seed 0, as `PromotionPolicy` declares them. Every solve runs under
`measurement_optimization_config()` (deterministic limit 5.0), and the record carries the solver
block: how many solves were proved and how many returned an incumbent.

## The comparator that decides, and what each gate licenses

| Gate | Statistic | Passes when | Licenses |
| --- | --- | --- | --- |
| G1 | R1, offset 0, top-40 population: paired difference in absolute error, candidate minus control | the interval's upper end is below zero | using the multiplier for the **later weeks** of member window plans, with the stated limit on the page rewritten to say what the later weeks now know |
| G2 | R2: paired net points per decision, candidate minus control | the mean is at least `PromotionPolicy.min_mean_improvement` (0.5) and the interval's lower end is above zero | opening a candidate declaration for the operational control under `candidate_declaration_review.md`. It promotes nothing by itself |
| G3 | R3: paired net points per decision, rolling H = 3 minus weekly, both under the candidate | the interval's lower end is above zero | revisiting the member-facing sentence that planning ahead did not beat the weekly decision. Until then that sentence stands |

G1 does not need G2. A better later-week number may be shown to a member in a window plan
without any claim that the weekly control should change.

## Power, said before the run

147 paired decisions. `planner_horizon_rolling` reports a standard error of 1.53 over 66
three-week windows, which implies a paired standard deviation near 12 points a window, or about 7
a decision. At 7 to 8 points a decision the standard error of a mean over 147 decisions is about
0.6 to 0.7. G2
asks for 0.5 with an interval clear of zero, so an effect near 1.5 points a decision would be
seen and one near 0.5 would not. A null on G2 is therefore weak evidence of no effect, and the
record will say so in those words. R1 has tens of thousands of player rows and is not limited
this way.

## Falsifiers, written before any measurement runs

- If G1 fails, the lane closes: later weeks stay the first week's numbers, the page keeps
  today's stated limit, and goal-based ratings are not retried. A retry needs information this
  candidate did not have (for example shot-based ratings), under its own protocol.
- If R1 shows the candidate's bias growing with the offset faster than the control's, the
  multiplier is not used beyond the offset where that starts, whatever G1 says at offset 0.
- If any rating reads a match of the decision gameweek or later, the run is void. A test
  holds this: a decision's ratings are unchanged when every later row of the panel is altered.

## What the record will contain

`docs/opponent_aware_projection.json` and its markdown twin, with a row in
`measurements_index.md`: the three readings with their intervals, the gate table with pass or
fail beside each statistic, the solver block, the frozen parameters, the position shares and the
home factor as measured, `locked_holdout_accessed: false`, and the elapsed time. Per-fold
evidence goes to `artifacts/` and is not committed.

## Deliberate exclusions

No tuning of the half-life, the shares or the home factor on these readings. No player-level
opponent effects. No price changes over the horizon. No chips in R2 or R3. No reading of the
2026-27 live season: that is the live projection audit, under its own protocol.
