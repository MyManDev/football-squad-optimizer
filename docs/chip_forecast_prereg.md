# Chip forecast: design and protocol

Status: design fixed and measurement pre-registered on 2026-09-19, on the owner's decision in
#659 that the system should say in which gameweek each chip a member holds is best played.
No measurement under this protocol has been run. This document changes no plan, price or live
control. Tracking issue: #659.

Amended on 2026-09-19, before any run, after the owner's review of the design: a fifth arm
without the reservation, and a weekly record of what each chip rule saw. Both are marked
below. Nothing else changed, and no chain had been walked when this was written.

## What is asked, in one sentence

For every chip a member still holds, say either "play it this gameweek" or "hold it, and this
is the gameweek the rule currently points at", with the expected points behind both, and be
honest about what that forecast rests on.

## What is already measured, and what it rules out

| Record | What it says |
| --- | --- |
| `season_chain`, `season_chain_value`, `season_chain_hybrid`, `season_chain_freehit` | Over four development seasons walked as chains, chips are worth about a hundred points a season against never playing one: all four chips **+103** under the calendar rule and **+114** under the hybrid rule. Most of it is the wildcard (+60 to 65, hits avoided); bench boost +11 to 17, triple captain +3 to 11, free hit +9 to 17. |
| the same records | The rule that earned it is a **weekly** one. Each week a chip is played only if what it adds this week exceeds a **holding value** (bench boost 20, triple captain 18, wildcard 12, free hit 15 points), and under `hybrid` the bench boost is offered only in a double gameweek and the free hit only in a gameweek where some team is blank or doubles. |
| `transfer_discipline_value_rolling` | A multi-week planner holding chips inside a rolling window **does not lead**: 1968 against 2016 and 2018 for the weekly controls. Letting the member's five-week window place the chip is the measured loser. |
| `chip_bayesopt`, `season_chain_tuned` | A search over the holding values found other constants; against `hybrid` they gained **+0.51 a week with an interval of [-1.14, +2.13]**. Nothing was promoted: the constants are not sharp, the rule is. |

So the forecast is **not** "open the member window to chips". `advice.py` hands every member
solve an empty chip availability for a stated reason (`NO_CHIP_LIMIT`: a finite window counts
nothing for holding a chip back, so a planner that could reach one would spend it), and the
rolling record above is that reason measured. The forecast is the weekly rule, applied to the
member's own squad, plus the calendar the rule reads.

## What is new this season and unmeasured

2026-27 has **two sets of chips**: each of the four is playable once in gameweeks 1 (wildcard
and free hit: 2) to 19 and once in 20 to 38. Every record above was measured with one bench
boost, one triple captain and one free hit for the whole season. Two consequences:

1. **Waiting is worth less.** Twice the chips over the same weeks means fewer good weeks per
   chip, so a threshold measured for one set is too high for two.
2. **A chip not played by the end of its half is lost.** A fixed threshold can hold a chip
   until it expires worthless. The threshold has to reach zero by the last gameweek of the
   half.

No development season has this rule. That is what the measurement below is for.

## The rule the forecast states

For member `m` deciding gameweek `t`, and a chip `c` held in the half that ends at gameweek
`L` (19 or 38):

- `gain(c, t)`: the points `c` adds if played this gameweek, against the member's own
  one-week plan without it. The product already computes this for a chip the member chooses
  (#603, #646, #647); the forecast computes it for every chip held.
- `threshold(c, t)`: what waiting is worth. Two candidates, one of which the measurement
  selects:
  - **fixed**: the recorded holding value `H(c)` until `L`, as measured for one set;
  - **decaying**: `H(c) * (L - t) / (L - s)`, where `s` is the first gameweek of the half, so
    it starts at `H(c)` and is zero in the last gameweek of the half.
- **Reservation**, as in `hybrid`: the bench boost is considered only in a double gameweek and
  the free hit only in a gameweek where some team is blank or doubles. In the last gameweek of
  the half the reservation is lifted, because a reserved chip that is not played then is lost.
- **Play now** when the reservation allows it and `gain(c, t) > threshold(c, t)`. Otherwise
  **hold**.

When the verdict is hold, the forecast names the gameweek the rule currently points at:

- **Triple captain and bench boost**: for each later gameweek `w` of the half, the gain is
  estimated from the member's present squad and today's projection scaled by each club's
  fixture count in `w`, which is how the product already projects later weeks
  (`live/horizon.py`). Triple captain: the best scaled projection in the squad. Bench boost:
  the scaled projections of the present bench. The named gameweek is the first `w` where that
  estimate exceeds `threshold(c, w)` under the reservation. No solve is needed.
- **Free hit**: the structured gameweeks (a blank or a double for some club) the published
  calendar shows before `L`, in order. No later gain is estimated, because a free hit's gain is
  a whole-squad solve per member per week, and nothing here spends that.
- **Wildcard**: no gameweek is named. Its value is a rebuild, which depends on how far the
  squad has drifted and not on the calendar; the card says the threshold and this week's gain.

Every later-week estimate carries the same sentence the window plans carry: later weeks repeat
this week's projection over the fixture calendar; they are not a forecast of those weeks. The
forecast is recomputed at every publish, from the squad and the calendar of that capture.

## What the card may say

Expected points and gameweeks, nothing else. No probability, percentage, chance, odds or
likelihood in either language. Until the measurement below has a verdict, the card states the
rule and its source ("a rule that was worth about a hundred points a season over four past
seasons on the system's own squad, with one set of chips; this season has two") and claims no
gain for the member. The planner never plays a chip for a member; the member's own chip choice
and its computation stay exactly as they are.

## The measurement

**Question.** Under two sets of chips, does the decaying threshold realize more than the fixed
one, and do both still beat never playing?

**Population.** The four development seasons, 2021-22 to 2024-25, each walked as one chain at
lookahead 1 with the `hybrid` policy, exactly as `season_chain_freehit` ran them, except for
the chip windows: every chip gets two windows, gameweeks 1 to 19 and 20 to 38 (wildcard and
free hit from 2), which is this season's rule laid over those seasons' fixtures. The locked
2025-26 season is not loaded; the runner names its seasons.

**Arms.** `off` (no chips); `fixed` (holding values bench boost 20, triple captain 18, wildcard
12, free hit 15, the constants of the committed chain records, constant to the end of each
half); `decaying` (the same constants, linear to zero at the end of each half, reservation
lifted in the last gameweek of the half). One further arm as a floor: `planner` (every open
chip offered every week with no holding value), which is "play it as soon as it helps".

*Amendment.* A fifth arm, `threshold_only`: the decaying thresholds with no reservation at
all. The reservation was measured with one bench boost for a whole season, where a double
gameweek was certain to come. In a half that ends at gameweek 19 a double may never come, and
then `decaying` holds the bench boost to the half's last gameweek and plays it there whatever
it adds. `threshold_only` asks whether the reservation still pays under two sets.

**Statistics.** Per arm: net season points, chips played and chips that expired unplayed, per
season and pooled. The comparison that decides: `decaying - fixed`, paired by gameweek within
season, with the 90 percent season-aware block bootstrap the chain records already use. Beside
it, `fixed - off` and `decaying - off`, to say whether two sets are still worth about what one
set was.

*Amendment.* `decaying - threshold_only`, read the same way, decides whether the forecast keeps
the reservation: it keeps it when the pooled difference is positive, and drops it otherwise,
again without calling four seasons a proof. Every chain also records, for every gameweek, what
its decision expected of its captain and of its bench (`captain_projected_points`,
`bench_projected_points`), beside what they realized. That is what a triple captain and a
bench boost would have been expected to add that week, at no extra solve. It is not read for
any verdict here. It is the input of the next step: a threshold computed by backward induction
over the remaining gameweeks of a half from the distribution of those weekly values by kind of
gameweek (single, double, blank), in place of the linear decay. That step gets its own
protocol before it is run.

**Decision, fixed now.** The arm with the higher pooled net is the rule the forecast uses. Four
seasons cannot separate arms that differ by a point a week, and the record will say so rather
than call a winner "better": if the interval of `decaying - fixed` contains zero, the forecast
uses `decaying` anyway, for the structural reason that it cannot let a chip expire, and the
card's evidence sentence quotes `decaying - off` with its interval and nothing more. If
`decaying - off` does not exclude zero, the card says the rule's worth under two sets was not
established, and states only the rule.

**Declared before running.** I expect `fixed` to let chips expire in most halves, `decaying` to
play nearly all of them, and `decaying - fixed` to be positive and mostly made of those
expiries. I expect both to beat `off` by more than a hundred points, because there are twice
as many chips.

**Solver.** `measurement_optimization_config()` (deterministic limit 5.0, #590), and the record
carries `solver_record`. Nights only, never Tuesday or Friday.

**Limits, stated in the record.** The chains are the system's own squad, not a member's: what
transfers to a member is the rule, not the number. Those seasons' managers had one set of
chips, so ownership and prices in the archive reflect one-set behaviour; the emulation changes
our rule, not the world around it. The later-week estimates for triple captain and bench boost
are not part of this measurement: the chain decides week by week from that week's own
projection, which is what the card's "play now" verdict rests on; the "points at gameweek N"
line is a reading of the calendar and is labelled as one.

## Work, in order

1. This document (docs only).
2. The decaying threshold and the lifted last-week reservation in the chain, behind the
   existing chip policy switch, with the runner's two-window rule; tests on synthetic seasons.
   Touches `experiments/` and the runner only.
3. The measurement, as its own pull request with its index row.
   *Amendment.* When the rule names a gameweek inside a member's three- or five-week window,
   the window plan may be solved with the chip **forced** in that gameweek
   (`ChipAvailability.forced` exists). The window then prepares for a week already decided
   by the weekly rule, which is what a window is good at; it never decides whether to spend
   the chip, which is what it was measured to be bad at. The Top 100 export is not an input
   anywhere in the forecast: it reports last gameweek's elevens, not this gameweek's chips.
   It may serve later to score our timing against when those managers played theirs.
4. `application/chip_forecast.py`: the pure function from a member's squad, the capture's
   projection, the calendar and the chips held to the forecast document, and its contract. No
   solve beyond the chip gains the product already computes. This is the first change that
   touches the product, and it lands only after 3 has a verdict.
5. Publication, the on-demand path and the card: Astra, from that contract. Ported from
   `codex/phases-0-1-2` only where it fits; that branch's `member_planning_policy_v3` switch
   and its scoreboard recovery stay rejected.
6. Scoring afterwards: the advice record holds every published document, so a recorded
   forecast is scored against what a member's chips actually did, the way price honesty is.
   Its protocol is written when the first forecast has been published, not before there is
   anything to score.
