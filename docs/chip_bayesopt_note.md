# Chip holding values and planning hit cost: Bayesian search on the season chain

Artifact: `chip_bayesopt.{json,md}` (contract `chip_bayesopt_v1` on
`deterministic_policy_bo_v1`). Runner: `scripts.run_chip_bayesopt`. Measurement only; the
2025-26 holdout was not read; nothing here changes an operational default.

## What was searched

The season chain (`season_chain_v1`, lookahead 1, hybrid chip policy: bench boost reserved
for doubles, triple captain / wildcard / free hit offered and held by their holding
values, `naive_calendar_scaling_v1`) walked over the four development seasons, for five
knobs the earlier one-at-a-time measurements left as constants:

| Factor | Grid | Reference (season chain note) |
| --- | --- | --- |
| `bboost_hold` | 0..30 step 5 | 20 |
| `threexc_hold` | 0..30 step 5 | 18 |
| `wildcard_hold` | 0..24 step 4 | 12 |
| `freehit_hold` | 0..20 step 5 | 15 |
| `planning_hit_cost` | 4..8 step 1 | 4 (the rule's cost) |

Objective per candidate: **mean season net minus one standard deviation across the four
seasons** (season-robust; a candidate that wins one season and loses three is not a
candidate). Twenty evaluations: eight maximin initial-design points, twelve
expected-improvement points; each evaluation walks four seasons in parallel workers
(solver limits: 8 s deterministic / 60 s wall per solve; ~34 min in total).

## What it found

- **Recommended candidate**: `bboost_hold=0, threexc_hold=20, wildcard_hold=24,
  freehit_hold=0, planning_hit_cost=7` — season nets 2097 / 2122 / 1952 / 2044, mean
  **2053.8**, spread 65.1, robust score **1988.6**.
- Against the recorded hybrid reference (holdings 20/18/12/15, hit cost 4: 2085 / 2089 /
  1933 / 2033, mean 2035.0, robust 1972.1) the candidate is **ahead in all four seasons**
  (+12, +33, +19, +11; mean **+18.8**, about 0.9% of a season). Four seasons is too few
  for an interval on that; the sign agreement is the whole of the evidence.
- The surface is flat where it matters. Iterations 15 and 17 (hit cost 7, high wildcard
  hold, `threexc_hold` 15-20) tie at mean 2054; the hit-cost-4 candidates sit at 2003
  on average with roughly double the season spread (130 vs 50-70). Most of the "robust"
  gain is variance reduction from a planning hit cost above the rule's 4, not a mean
  shift — the same picture as the transfer-discipline note, now with chips on the board.
- **`wildcard_hold=24` is the upper edge of the grid** (13 of 20 evaluations sat there;
  0 → 2001, 16 → 2015, 24 → 2028 mean net). The search wants a higher wildcard holding
  value than it was allowed to test; the grid must be widened before this is believed.
- `bboost_hold` is nearly inert under the hybrid policy (the bench boost is reserved
  for doubles regardless), and `freehit_hold=0` was preferred: the free hit is played
  wherever the planner sees any gain in a structured week, which the free-hit note
  measured at +9..+17 per season.

## What it does not show

No promotion. The candidate is the next input to a full season-chain comparison (all
chip modes, bootstrap intervals, and the lookahead-3 capped rolling planner where the
discipline evidence lives) and to the live GW2+ chip recommendation once the handoff is
in place. Next steps if it holds up: widen `wildcard_hold` beyond 24, re-run under
`--chip-mode value` (planner-only reservation), and add the candidate as a named chip
mode to `run_season_chain_seasons` so the bootstrap can compare it with `hybrid`
directly.

## Follow-up (2026-08-18, later): the candidate on the chain, a wider grid, value mode

Artifacts: `season_chain_tuned.{json,md}` (the candidate as the chain runner's `tuned`
chip mode — hybrid policy, holdings 0/20/24/0, planning hit cost 7 — against `hybrid`
and `off` on the four seasons, 8 s deterministic / 60 s wall, moving-block bootstrap),
`chip_bayesopt_wide.{json,md}` (hybrid, `wildcard_hold` grid widened to 0..40),
`chip_bayesopt_value.{json,md}` (the same search under the `value` chip policy).

**The candidate on the chain.** `tuned` reproduces the search's season nets exactly
(2097 / 2122 / 1952 / 2044; `hybrid` reproduces the recorded 2085 / 2089 / 1933 / 2033), so
the walk is deterministic and the search measured what the chain measures. Paired by
gameweek: tuned − hybrid = **+0.51 points a week, 90% block-bootstrap [−1.14, +2.13]**,
positive-week share 0.43, +18.8 a season. The four season signs agree, the weekly
evidence does not leave zero. Where the season difference comes from: hits (60 vs 172
hit points over the season for 2021-22, 32 vs 136, 20 vs 84, 12 vs 72) — the candidate
transfers less and scores fewer raw points, and the net is a wash within noise. Against
`off`, tuned is +3.62 a week [+1.88, +5.57] and hybrid +3.11 [+1.82, +4.69]: the chips
are the effect, the tuning is not.

**A wider grid moves the optimum, which says the surface is flat.** With `wildcard_hold`
allowed to 40 the robust optimum is `bboost=10, 3xc=5, wildcard=28, freehit=20, hit
cost 8` — mean net 2072.5 (2145 / 2156 / 1911 / 2078), spread 97.9, robust 1974.6: a
higher mean than the first run's candidate (2053.8) but a wider season spread, so a
*lower* robust score. `wildcard_hold=40` was tried three times and lost (2021, 2029,
1948 mean net); the wildcard's value stops rising around 28. `freehit_hold=20` (against
0 in the first run) and `3xc_hold=5` (against 20) show the same thing: the factors trade
against seasonal variance, not against each other, and 20 evaluations over four seasons
cannot separate candidates whose means differ by less than the season-to-season spread
(~60–100 points).

**Value mode** (every chip offered, all held at their values; no bench-boost reservation;
wide grid): robust optimum `bboost=0, 3xc=10, wildcard=32, freehit=20, hit cost 7` —
season nets 2092 / 2117 / 1993 / 2057, mean 2064.8, spread **46.6**, robust **2018.2**:
the best robust score of the three searches (hybrid 1988.6, hybrid-wide 1974.6), ahead
of the recorded hybrid reference in all four seasons (+7 / +28 / +60 / +24, mean +30) and
with the smallest season-to-season spread. What the three searches agree on, and only
that: a **planning hit cost of 7–8** (hit cost 4 averages 1973–2003 mean net in every
search, 7–8 averages 2020–2065), a **free-hit holding value at the top of the grid (20)**
in both wide runs, `wildcard_hold` around **28–32** (the value stops rising before 40),
and `bboost_hold` near zero. `3xc_hold` is not identifiable (5, 10, 20 tie).

Value-mode's advantage over hybrid, if real, says the bench-boost *reservation* costs
more than it protects once the holding values are set — but it is the same +30 a season
that the chain could not separate from zero for `tuned` (+18.8), so it goes onto the
chain next as its own named mode, not into a default.

What this leaves: no promotion, no operational change. The transferable finding is the
one the discipline note already had — a planning hit cost above the rule's 4 reduces
hits and season-to-season variance at no measurable cost in mean — and it should be
measured where the discipline evidence lives (the lookahead-3 capped rolling planner)
before it becomes a default. The chip holding values themselves are not identifiable
from four seasons.
