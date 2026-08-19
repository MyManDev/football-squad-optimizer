# Reading the transfer-discipline measurement

Companion to [transfer_discipline.md](transfer_discipline.md) (lookahead 1, full 3 × 3 × 3
factorial, contract `transfer_discipline_seasons_v1`) and
[transfer_discipline_rolling.md](transfer_discipline_rolling.md) (lookahead 3, the
2 × 2 corner), both from `scripts.run_transfer_discipline_seasons` on the season-long
chain (`docs/season_chain_note.md`) with chips under the double-gameweek reservation
rule, deterministic budget 8.0, run one process per season and merged.

The chains had shown the weekly control paying ~40 hits a season under naive projections
and the rolling planner far more. This asks whether three planner-side disciplines — none
of which change the game's rules; the sheet still charges four points a hit — buy
anything: a **planning hit cost** above four (a hit threshold, a winner's-curse haircut on
projected gains), a **per-gameweek transfer cap** (a wildcard week is exempt), and a
**terminal value for a banked free transfer** (so a small gain no longer spends one for
nothing). Every cell is compared with the rule cell (cost 4, no cap, value 0) at the same
lookahead: paired season nets and per-gameweek differences with a season-aware
block-bootstrap interval.

## Lookahead 1 (the weekly control): discipline does not pay on average

Rule cell mean net **2008** (hits 144, 91 transfers). Main effects — mean season net delta
versus the rule cell over the other two factors:

| Planning hit cost | Δ | hits | | Transfer cap | Δ | hits | | Banked value | Δ | hits |
| --- | ---: | ---: | --- | --- | ---: | ---: | --- | --- | ---: | ---: |
| 4 | −27 | 71 | | none | −21 | 84 | | 0 | −25 | 41 |
| 6 | −23 | 37 | | 2 | −15 | 41 | | 1 | −26 | 43 |
| 8 | −13 | 17 | | 1 | −28 | 0 | | 2 | −13 | 41 |

Every discipline removes hits — a cost of 8 halves them, a cap of 1 removes them all —
and every one gives back at least as much in selection. The best cells (cost 8, cap 2,
value 1–2: +13 / +23 per season) have intervals that include zero; the only cells whose
intervals exclude zero are the banked-value-only cells at the rule's cost, and they are
**negative** (−37 [−1.97, −0.27 per week], −42 [−2.10, −0.38]): a free transfer held for
a later week loses more to a stale squad than it saves in later hits.

The seasons disagree in sign, and that is the finding: cost 8 without a cap is +84 / +96
in 2022-23 / 2023-24 and **−246** in 2021-22; cap 1 is +35 in 2023-24 and −116 in
2021-22. In 2021-22 — a season of postponements and doubles — the hits the rule cell
takes are the moves that follow the calendar, and every discipline pays them back as
staleness. Under naive calendar scaling, the weekly control's hits are, over four seasons,
worth about what they cost; a threshold trades hit points for selection points roughly
one for one, and which side wins is a property of the season.

## Lookahead 3 (the rolling planner): a cap turns it into something

Rule cell mean net **1877** (hits 249, 117 transfers) — the churn the rolling measurement
found. Discipline here is different in kind:

| Cell | Mean net | Hits | Δ vs rolling rule | Weekly [90%] |
| --- | ---: | ---: | ---: | --- |
| cost 8, no cap | 1966 | 127 | **+89** | [+1.13, +4.22] |
| cost 4, cap 1 | 2016 | 0 | **+140** | [+2.18, +5.78] |
| cost 8, cap 1 | 2017 | 0 | **+140** | [+2.15, +5.52] |

Positive in every season (cap 1: +331, +93, +109, +25). Capped at one transfer a week, the
rolling planner is worth **2016** a season against the weekly control's **2008** — the
first configuration in any planner measurement to draw level with the weekly baseline
(+32, +44, +70, **−113** by season; per-gameweek mean +0.22 [−1.14, +1.39], 147 paired
weeks). Set against the *capped* weekly control (1984), the three-week horizon is worth
**+33** a season (+148, +39, +35, −90): once churn is off the table, planning three weeks
ahead beats deciding one week at a time in three seasons of four. That is the first
positive evidence for a horizon in this project, and it is conditional — on the cap, on
the reservation rule, and on 2024-25 being the season it is not true.

## What it says

1. **For the live weekly control, keep the rule** (hit cost 4, no cap, no banked value).
   No discipline setting is robustly better under this projection; the ones that look
   better in two seasons look worse in a third, and the only interval-clean effect is a
   loss. What would change this is a projection whose early weeks are not inflated (the
   rule cell's hits cluster there) — a prediction-side matter — not a planner control.
2. **For the rolling planner, the cap is the missing piece.** Its loss was churn, and a
   one-transfer cap removes the churn without removing what the horizon sees; the capped
   rolling planner is level with the weekly control and ahead of the capped weekly
   control. This is the configuration to carry forward if a multi-week planner is ever
   promoted — and the measurement to repeat with the operational projection.
3. **Banked-transfer value is not worth having** at lookahead 1 (negative where
   significant) and was not measured at lookahead 3 in this run.

## Addendum (2026-08-18): the cap under other projections and chip modes

- **Calendar-blind control** ([transfer_discipline_blind_rolling.md](transfer_discipline_blind_rolling.md)):
  with no fixture-count scaling the one-transfer cap is still worth **+122** a season to
  the rolling planner (+270, +131, +147, −58; [+1.89, +5.18] per week). The finding does
  not depend on the naive scaling.
- **Holding-value chips** ([transfer_discipline_value_rolling.md](transfer_discipline_value_rolling.md)):
  with chips held at their option values instead of the calendar rule, the capped rolling
  planner reaches **1968** — +130 over its uncapped rule cell but **below** the capped
  rolling planner under the reservation rule (2016) and below the weekly control with the
  same holding values (2018; −81, +23, −140, 0 by season). A three-week horizon rarely sees
  a bench remainder or a captain clear the holding values, so bench boosts go unplayed and
  triple captains late; the calendar rule times them better for this planner. The answer to
  "does the capped rolling planner stay ahead once chip timing is improved by the option
  value?" is **no** — its edge over the weekly control was with the reservation rule, and
  it stays a draw (2016 vs 2008), not a lead.

## Caveats

- Four seasons; season heterogeneity is the dominant term at lookahead 1. Intervals are on
  weekly paired differences and rest on the block-bootstrap treatment of dependence.
- Naive calendar-scaling projection; the mechanism, not projection quality, is measured.
- Rolling solves are proven optimal in 35–76% of weeks at budget 8.0 (unproven weeks are
  FEASIBLE with recorded gaps and bias the rolling planner down, not up).
- Chip windows assumed as in the season chain; the free hit was not in these runs (it
  arrived with planner contract v2 afterwards); no auto-subs.

## What follows

- The season chain and the discipline factorial with the operational projection once an
  in-season projection producer exists (`projection_handoff_v1` is the interface).
- Lookahead 2 with the cap; the value-mode run is in the addendum above.
- Not changing the live control's transfer settings on this evidence.
