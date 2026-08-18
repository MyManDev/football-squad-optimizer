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
