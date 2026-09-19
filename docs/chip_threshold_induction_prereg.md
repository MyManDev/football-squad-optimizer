# Chip threshold by backward induction: protocol

Status: pre-registered on 2026-09-19. No measurement under this protocol has been run, and the
record it reads (`docs/chip_forecast_rule.json`) does not exist yet: no chain with the weekly
projected columns has been walked, so no threshold below has been computed for any real season
by anyone. This document changes no plan, price or live control, and it promotes nothing.
Tracking issue: #659. It is the step the amendment of `docs/chip_forecast_prereg.md` (#680)
announces as the use of the weekly projected columns, and of which it says that it gets its
own protocol before it is run.

## What is asked, in one sentence

Is a chip's holding threshold better computed, as what the best later gameweek of its window is
expected to offer, than drawn as a straight line to zero?

## What is already measured, and what is not

| Record | What it says |
| --- | --- |
| `season_chain`, `season_chain_value`, `season_chain_hybrid`, `season_chain_freehit` | Over four development seasons walked as chains, with one set of chips, a weekly rule that plays a chip only when it adds more than a **constant holding value** (bench boost 20, triple captain 18, wildcard 12, free hit 15) is worth **+103 to +114** a season against never playing one. Of that, bench boost is +11 to 17 and triple captain +3 to 11. |
| `transfer_discipline_value_rolling` | Letting a multi-week planner place the chip does not lead the weekly rule (1968 against 2016 and 2018). The threshold has to stay a weekly rule. |
| `chip_bayesopt`, `chip_bayesopt_wide`, `chip_bayesopt_value`, `season_chain_tuned` | A search over the constants found other constants and gained **+0.51 a week, interval [-1.14, +2.13]** against `hybrid`. The constants are not sharp; the surface is flat within the season spread. Nothing was promoted. |
| `terminal_value_study` | A Gaussian process pricing the whole squad state (chips in hand among its features) lost to the constants pooled and in all four held-out seasons. That was a fitted model of the season's remaining net points. It is not this: nothing is fitted here, and the quantity is one chip's option over one window. |
| `docs/chip_forecast_prereg.md` (#675, amended in #680), not yet run | Under this season's two sets of chips a constant can hold a chip until its window closes and it is lost, so the forecast's candidate threshold **decays linearly** to zero at the end of the half. The line is a shape chosen by hand. Its measurement (`chip_forecast_rule`) is pending. |

Checked before writing: `docs/measurements_index.md` and `src/squadopt/experiments/` hold no
stopping rule, no backward induction and no threshold computed from a distribution of weekly
values. The chip work so far is constants, a search over constants, and a line.

## The rule

A chip `c` is held in a window that ends at gameweek `L` (19 or 38). In gameweek `t` it would
add `g_t`. Holding it is worth the best later opportunity of the window, which is an optimal
stopping problem with a known last date:

    tau_L = 0
    tau_t = E[ max(g_{t+1}, tau_{t+1}) ]        for t < L

and the rule is: **play at `t` when `g_t > tau_t`**. At `L` the threshold is zero, as under the
linear decay, so a chip that adds anything is played before it is lost. Thresholds computed
this way are never negative and never rise as the window runs out; they step down as each good
gameweek goes by, where the line falls by the same amount every week whatever is ahead.

The expectation is over what the next gameweek could offer, and that depends on its **kind**:

- `double`: some club plays twice;
- `blank`: some club does not play, and none plays twice;
- `single`: every club plays once.

A gameweek that is both a double and a blank is a `double`. Both chips covered here are worth
what the squad's best few players are projected for, and those are the players who play twice,
whoever else sits the week out. A fourth kind would split a handful of structured gameweeks
into cells too small to average. The fixture table the chains use is built by counting
fixtures, so a club without a fixture has no row; a missing row is read as a blank.

The expectation is the **empirical mean** of `max(value, tau_{t+1})` over the recorded weekly
values of that kind. No distribution is fitted and there is no constant to choose. A kind that
has to be averaged over and has no value in the sample falls back to the pooled sample of all
kinds, and every record that carries thresholds lists where that happened.

**Two chips, not four.** The weekly chain record holds what a triple captain and a bench boost
would have been expected to add that week, at no extra solve: `captain_projected_points` (the
captain's projection, once) and `bench_projected_points` (the bench's projection). Those are
`g_t`. **The wildcard and the free hit are not covered**: what either would add is a
whole-squad solve per week, and that number is not in the weekly record. Under this protocol
they keep the linear decay and, for the free hit, its reservation, exactly as in the `decaying`
arm.

**Only what a decision could see.** The thresholds are computed from the projected columns.
The realized columns beside them (`captain_realized_points`, `bench_realized_points`) are never
an input: a threshold that learned from what captains went on to score would be tuned on the
outcome it is then judged by.

**No reservation for the two chips.** Under `hybrid` the bench boost is offered only in a
double gameweek. That reservation is a hand-made stand-in for what the recursion computes: with
a double ahead the threshold before it is high because the double's values are, and with no
double left it is not. So the `induction` arm offers the triple captain and the bench boost in
every gameweek of their window and lets the threshold do the holding.

The arithmetic is `src/squadopt/experiments/chip_threshold.py` (`classify_gameweek_kinds`,
`exercise_values_by_kind`, `induction_thresholds`, `window_thresholds`,
`leave_one_season_out_thresholds`), tested on synthetic samples with every expected number
derived by hand. It landed with this document and before any real value existed.

## The measurement

**Question.** Under two sets of chips, does the chain realize more with the induction
thresholds for the triple captain and the bench boost than with the linear decay?

**Population.** The four development seasons, 2021-22 to 2024-25, each walked as one chain at
lookahead 1 under this season's two-window rule (every chip once in gameweeks 1 to 19 and once
in 20 to 38, wildcard and free hit from 2), exactly as `scripts/measure_chip_forecast_rule.py`
lays it over them. The locked 2025-26 season is not loaded; the runner names its seasons.

**The thresholds, leave one season out.** The sample is the weekly projected values of the
`decaying` arm's chains in `docs/chip_forecast_rule.json` (`chains[]` with `variant ==
"decaying"`), the arm whose squads are nearest to the ones the new arm will hold. For season
`S` the thresholds are computed from the **other three seasons only**; the kinds of `S`'s own
gameweeks are read, because the calendar is what the rule is a function of. No value of `S`
enters a threshold `S` is walked with. The source arm is fixed now and does not change with
that record's verdict.

**Stage 1, no solve.** As soon as `docs/chip_forecast_rule.json` exists: the table of
thresholds per season, chip, half and gameweek, beside the linear decay from the constants 18
and 20, with the sample size per kind and every pooled fallback; and a **replay** on the
recorded weeks: the gameweek the induction rule would have played each of the sixteen chips in
(four seasons, two halves, two chips), which is the first gameweek of the window whose recorded
value exceeds its threshold, beside the gameweek the `decaying` chain played it in,
with the projected and the realized value of both gameweeks. The replay is descriptive. It
ignores that playing a chip in another week can move a transfer, so it carries no verdict. It
decides one thing: **if the replay plays all sixteen chips in the gameweek the `decaying` chain
did, the two rules are the same rule on these seasons, stage 2 is not run, and the record says
so.** The threshold table is committed before any `induction` chain is walked.

**Stage 2, the chains.** Arm `induction`: the `decaying` arm with two changes, the triple
captain's and the bench boost's thresholds read from the stage 1 table of that season, and no
reservation for those two. Wildcard and free hit as in `decaying`. It is compared with the
`decaying`, `threshold_only` and `off` chains of `docs/chip_forecast_rule.json`, which are not
walked again, provided the change that wires the arm shows a default chain unchanged week for
week; if it cannot, all four arms are walked in the same run.

**Statistics.** Per arm and season: net points, the gameweek each chip was played in, chips
that expired unplayed. The comparisons are `chain_comparison` as the chain records already use
it: paired by gameweek within season, 90 percent season-aware moving block bootstrap, 2000
resamples, block length 4. `induction - decaying` decides. Beside it, `induction -
threshold_only` (the same offering, only the threshold's shape differs) and `induction - off`.
If the pending chip forecast measurement drops the reservation, the forecast's rule is
`threshold_only`, and then `induction - threshold_only` is the comparison that decides; both
are reported either way.

**Decision, fixed now.** The linear decay is simpler, needs no sample and no calendar ahead of
the week being decided. It stays the forecast's threshold unless the interval of the deciding
comparison lies entirely above zero. A positive pooled difference whose interval contains zero
is recorded as "not separated" and changes nothing. A negative one is recorded as a negative.
In neither case is there a second attempt under this protocol with other kinds, another source
arm, a smoothed sample or a fitted distribution: each of those is a new rule and needs its own
protocol, written before its run.

**Declared before running.** I expect the thresholds to start a first half, where doubles are
rare, below the constants 18 and 20, so that induction plays both chips earlier in first
halves than the line does; and to sit close to the line's choices in second halves, where the
large doubles are and both rules wait for them. I expect the replay to differ from the
`decaying` chain in some of the sixteen windows, so that stage 2 runs. I expect `induction -
decaying` to be within a point a week of zero and its interval to contain zero, which by the
rule above leaves the linear decay in place. I expect `induction - off` to be clearly positive,
because any rule that plays eight chips beats playing none.

**Solver.** `measurement_optimization_config()` (deterministic limit 5.0, #590), and the record
carries `solver_record`. Nights only, never Tuesday or Friday.

## Limits, stated in the record

- **Four seasons.** Leaving one out leaves three seasons of weekly values, one per decision
  gameweek, of which the doubles and the blanks are a handful each. The thin cells are
  printed, not hidden, and four seasons cannot separate rules that differ by a point a week.
- **The system's own squad, not a member's.** What would transfer to a member is the rule,
  never a number measured here.
- **The calendar is known in hindsight.** Kinds come from the final fixture counts of past
  seasons, so the recursion knows in gameweek 3 of a double in gameweek 17. A live calendar
  announces most doubles a few weeks ahead. The `decaying` arm reads only the current week's
  kind, so this measurement favours induction, and a gain here is an upper bound on what a
  live rule recomputed at every publish from the published calendar would see.
- **The recursion assumes independent weeks.** Values of one kind are treated as exchangeable
  draws, across the weeks of a season and across seasons. A squad's captain is the same player
  for months, scoring rules changed between seasons, and the sample comes from chains whose
  squads the `decaying` arm's own chip plays shaped (a free hit week's captain and bench are a
  temporary squad's).
- **The bench boost's value is understated.** `bench_projected_points` is the bench of a plan
  that was not choosing its bench to be boosted. When the chip is on offer the planner may
  rearrange, so what it sees is at least that number. Thresholds built from the lower number
  play the bench boost somewhat early. The bias is known and is not corrected here.
- **Wildcard and free hit are not covered**, for the reason given above. A computed threshold
  for them needs their weekly value recorded first, which costs a solve per week per chain.
- **One set of chips in the archive.** Those seasons' managers had one set, so ownership and
  prices reflect one-set behaviour; the emulation changes our rule, not the world around it.

## Work, in order

1. This document, the arithmetic and its tests (one pull request; nothing measured).
2. #677 merges (the decaying threshold, the two-window runner, the weekly projected columns),
   and the chip forecast measurement is run and committed by the main session
   (`docs/chip_forecast_rule.json`).
3. A later pull request wires an `induction` threshold into the chain behind the existing
   `chip_threshold` switch, with a test that a default chain is unchanged, and adds the runner
   for stage 1 and stage 2. Touches `experiments/` and the runner only.
4. Stage 1 as a committed record (`docs/chip_threshold_induction.json` and `.md`, contract
   `chip_threshold_induction_v1`) with its row in `measurements_index.md`; then stage 2 in the
   same record, if stage 1 calls for it.
5. Only if the decision above replaces the line: `application/chip_forecast.py` reads computed
   thresholds in place of the decayed constants, in its own pull request, with the published
   calendar's kinds and not a past season's.
