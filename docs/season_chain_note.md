# Reading the season-long chain measurement

Companion to [season_chain.md](season_chain.md) (contract `season_chain_seasons_v1`,
chain contract `season_chain_v1`), the mechanical output of
`scripts.run_season_chain_seasons --lookaheads 1,3 --chips off,on,reserve
--deterministic-time-limit 8`, run as one process per season and merged with `--merge`.
It answers the two questions the windowed measurements
([planner_horizon_seasons_note.md](planner_horizon_seasons_note.md),
[planner_horizon_rolling_note.md](planner_horizon_rolling_note.md)) could not ask,
because a window starts from a fresh squad and cannot own a once-per-season resource:

1. What is a chip worth on the realized sheet, when the planner decides when to play it?
2. Does the rolling planner's transfer-hit churn turn into chip use once chips exist?

## Design

- Four development seasons, each walked **once as a chain**: opening squad optimized at
  the first decision gameweek (GW2; in-season features need one prior gameweek), then
  every later decision gameweek in turn with the state carried — squad, bank, banked free
  transfers, purchase prices, spent chips. 37 decisions per season (36 in 2022-23, whose
  GW7 was postponed).
- Six variants per season on the same opening squad, projection rule (naive calendar
  scaling), pool rule (top 20 + cheapest 8 per position, rebuilt weekly, always including
  the held squad), sell rule (purchase price plus half of any rise, rounded down to a
  tenth), and scoring (starters plus the captain again; no automatic substitutions):
  lookahead **1** (the myopic weekly baseline) and **3** (rolling: re-plan weekly, apply
  the first week) × chips **off** / **on** (every open chip offered to the planner) /
  **reserve** (bench boost and triple captain offered only in double gameweeks; wildcard
  as under *on*).
- Chip windows are **assumed** for the development seasons — one wildcard per half with
  the first expiring after GW20 / 16 / 20 / 19 (2021-22 … 2024-25), one bench boost and
  one triple captain per season — and recorded in the artifact as an assumption. Free hit
  is outside the planner's contract and outside this measurement. Free-transfer bank cap
  2 for 2021-22 … 2023-24 and 5 for 2024-25.
- Deterministic solver budget 8.0 per solve, wall clock 60 s. Statistics: the season net
  is the headline (four observations); the per-gameweek paired differences carry the
  interval — a season-aware moving-block bootstrap (blocks of four consecutive weeks,
  because a carried squad makes weeks dependent), 90%.

## The numbers

Season nets (realized points minus hit points), mean over the four seasons:

| Variant | Realized | Hits | **Net** | Transfers | Chip gains (mean per season) | Proven solves |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| L1 chips off (myopic baseline) | 2088 | 167 | **1921** | 78.5 | — | 1.00 |
| L1 chips on | 2132 | 142 | **1990** | 90.5 | WC +65, BB +11.5, TC +8.0 | 0.99 |
| L1 chips reserve | 2152 | 144 | **2008** | 90.8 | WC +63, BB +16.8, TC +10.5 | 1.00 |
| L3 chips off (rolling) | 2069 | 304 | **1765** | 112.8 | — | 0.55 |
| L3 chips on | 2076 | 265 | **1811** | 120.0 | WC +59, BB +13.2, TC +3.2 | 0.61 |
| L3 chips reserve | 2126 | 249 | **1877** | 116.8 | WC +62, BB +17.5, TC +11.0 | 0.61 |

Paired against the myopic baseline (season delta = difference of season nets; weekly
mean ± SE and the block-bootstrap interval are on the per-gameweek paired differences):

| Variant vs L1 chips off | Season delta by season | Mean season delta | Weekly mean ± SE | 90% interval |
| --- | --- | ---: | ---: | --- |
| L1 chips on | +49, +16, +50, +162 | **+69** | +1.88 ± 0.76 | [+0.56, +2.99] |
| L1 chips reserve | +124, +34, +21, +171 | **+88** | +2.38 ± 0.69 | [+1.31, +3.75] |
| L3 chips off | −296, −175, +2, −156 | **−156** | −4.25 ± 1.06 | [−6.35, −2.79] |
| L3 chips on | −253, −116, −37, −35 | **−110** | −3.00 ± 1.03 | [−5.08, −1.56] |
| L3 chips reserve | −175, −15, −18, +33 | **−44** | −1.19 ± 0.95 | [−2.93, +0.16] |

Chips against no chips at the same lookahead: L3 on vs L3 off **+46** per season
(hits −39; interval [−0.50, +2.95] per week); L3 reserve vs L3 off **+113** (hits −55;
[+1.66, +4.73]).

## What it says

**1. Chips are worth roughly 70–90 net points a season under this projection, and most
of that is the wildcard.** Two wildcards buy 60–65 points of avoided hits per season
(15–20 transfers rebuilt for free); the bench boost 11–17; the triple captain 3–11. The
interval for chips-on-versus-off excludes zero for the myopic baseline in both chip modes.
The triple captain is small because the naive projection's captain is not reliably the
week's big scorer — its realized captain points on the played week were 2, 7, 4, 29 under
the reserve rule; the chip's value is the projection's captaincy skill, not the mechanism.

**2. Timing is the whole triple-captain / bench-boost question, and a finite horizon
cannot see it.** With every chip offered (*on*), the myopic baseline plays bench boost in
GW2 and the triple captain and first wildcard in GW3–4 in every season — a chip worth
anything now is played now, because a one-week (or three-week) horizon does not know the
season continues. The rolling planner holds the bench boost for a double it can see in
two seasons (2023-24 GW25, 2024-25 GW24), spends it by GW16 in the other two, and spends
the triple captain in GW4 or GW7 everywhere. The
**reserve** rule — offer bench boost and triple captain only in double gameweeks, the
common human rule — is worth another **+18 (myopic) / +66 (rolling)** per season over
*on*, and it is what makes chips-on-versus-off significant for the rolling planner. The
mechanism therefore needs either a season-scale horizon or an explicit option value for an
unplayed chip; the reserve rule is the cheapest stand-in, and this measurement is its
first evidence.

**3. The rolling planner's churn does not turn into chips; it stays churn.** With chips
on, the rolling planner still pays 265 hit points a season against the myopic baseline's
142 (its transfers rise from 113 to 120), and loses **−110** net per season. The wildcard
absorbs 15–20 of its transfers, and the planner spends the saving on more transfers
elsewhere. Reservation narrows the gap to **−44** [−2.93, +0.16 per week] — the closest a
multi-week planner has come to the weekly baseline in any measurement — but the sign is
still negative in three seasons of four. The finding of the rolling-horizon measurement
stands at season scale: under naive calendar scaling, re-planning weekly buys selection
and pays more than it buys in hits, chips or no chips.

**4. Season scale confirms the window-scale verdict and adds the number the windows
could not give.** The rolling planner without chips loses **−156** net per season
(−4.25 ± 1.06 per week), the same structural loss the 66-window measurement showed at
−2.30 per three-week window, now paid over a whole season with a carried squad and the
game's sell rule.

## Caveats

- **Four seasons are four observations** for season totals; the intervals are on weekly
  paired differences and rest on the block-bootstrap treatment of dependence.
- **Chip windows are assumed** for the development seasons, not read from a capture. Only
  the wildcard split moves under a different assumption; bench boost and triple captain are
  season-wide either way.
- **The projection is the naive rule**, not the operational control's live projection; the
  numbers measure the planning and chip mechanism under it. Early-season projections are
  visibly inflated (a form window of one to three gameweeks), which is where the myopic
  baseline's own hits come from.
- **No automatic substitutions, no free hit, no auto-captain rules.** A blank-team squad
  member scores zero (carried rows: 12–52 player-weeks per chain, most in 2021-22; none
  unexplained).
- **Solve quality**: the rolling planner is proven optimal in 55–61% of its weeks at budget
  8.0 (2021-22, with its many doubles, 32–46%); the myopic baseline in ≥ 99%. Unproven weeks
  are FEASIBLE with recorded gaps; they bias the rolling planner down, not up.
- **Two planner fixes fell out of building this**: the chip tie-break now defers an
  equal-value chip to the later week (a rolling planner re-decides it next week), and the
  free transfers consumed under a wildcard are pinned in both directions (a free variable
  in a horizon's last week made the extraction verification fail).

## Addendum (2026-08-18): a holding value instead of the calendar rule

[season_chain_value.md](season_chain_value.md) adds a third chip mode at lookahead 1:
**value** — every open chip offered, each held at a terminal option value
(`TransferPlanningConfig.chip_holding_value_points`: bench boost 20, triple captain 18,
wildcard 12 points; an assumption calibrated to the naive projection's scale, where a
captain projects ~10 and a bench remainder ~10 in a single week and doubles roughly
double them). Same seasons, opening squads, and protocol.

| Variant vs L1 chips off | Season delta by season | Mean | Weekly [90%] | Chip gains (mean) |
| --- | --- | ---: | --- | --- |
| reserve (calendar rule) | +124, +34, +21, +171 | **+88** | [+1.31, +3.75] | WC 63, BB 17, TC 10.5 |
| value (holding value) | +70, +34, +185, +98 | **+97** | [+1.24, +3.86] | WC 76, BB 11.5, TC 17 |

- **Triple captain**: the holding value times it better than the calendar rule — played
  on the season's largest projected captain week (a double, GW22–36), realizing 20 points
  in three seasons of four against the rule's 2–29.
- **Wildcard**: held past the opening weeks (played GW5–9 instead of GW3) and again in
  the second half at a larger rebuild (9–13 moves), worth 64–92 against ~63.
- **Bench boost**: still played in GW2 in every season. The bench remainder projected in
  GW2 exceeds 20 because a one-gameweek form window inflates early projections; no
  constant holding value stands against that, and the calendar rule (a double only) does.
- Net: **value ≥ reserve on average (+9.5 per season)**, better on two chips, worse on one;
  the intervals overlap. The obvious combination — holding values for the transfer and
  captain chips, the calendar rule for the bench boost — is untested and the next cheap
  step; a projection that does not inflate the opening weeks would remove the reason for it.

## Addendum (2026-08-18, later): hybrid policy, calendar-blind control

**Hybrid chip policy** ([season_chain_hybrid.md](season_chain_hybrid.md)): the bench boost
reserved for doubles, triple captain and wildcard held at their holding values. Lookahead 1,
same protocol: **+102 per season** over no chips (+59, +67, +191, +90; weekly
[+1.50, +4.15]) against reserve +88 and value +97. Best of the three on average, and each
still has a hole: hybrid burned the triple captain in 2021-22's GW2 (the inflated opening
captain clears 18) and never found a bench-boost double in 2024-25 after GW25. The three
policies sit within ~15 points of each other; the ordering is not settled by four seasons.

**Calendar-blind control** ([season_chain_blind.md](season_chain_blind.md), projection rule
`control_calendar_blind_v1`: the operational control exactly as it is evaluated, no
fixture-count scaling, a double projecting like a single). This answers what the naive
calendar scaling in every chain measurement is worth:

| Lookahead 1 | scaled (naive_calendar_scaling_v1) | calendar-blind | difference |
| --- | ---: | ---: | ---: |
| chips off | 1921 (hits 167, 78 transfers) | 1863 (hits 89, 59 transfers) | **+58** |
| chips reserve | 2008 | 1912 (+48 over blind off) | +96 |
| chips value | 2018 | 1915 (+52 over blind off) | +103 |

Knowing the calendar is worth about **58 net points a season** to the weekly control —
its calendar-chasing hits pay for themselves — and roughly **halves the value of chips**
when it is missing (the blind planner never triples a captain under the holding value,
because no captain ever projects a double). The rolling planner's cap-1 result holds
blind as well (+122 per season over the uncapped rolling rule; [+1.89, +5.18]).
This is the case for the live in-season projection being calendar-aware: the
opening-week control is calendar-blind by construction, and a GW2+ handoff that is not
calendar-aware would leave both the transfer and the chip decisions half-blind.

## What follows

- Live path: the weekly baseline stays the operational control. Chips can be recommended
  in the live path only with a reservation rule or an option value; the reserve rule has
  evidence now, an option value does not.
- Planner: transfer discipline (a hit threshold or a discount on hits in rolling mode) is
  still the open lever; this measurement narrows where it must act — the churn is not
  chip-shaped.
- Prediction side: the triple captain's value is captaincy skill; a projection whose top
  captain is right more often is where that chip's points are.
- Later: free hit as a separate contract version; chip windows from `season_rules_v1`
  for the live season instead of the assumed table.
