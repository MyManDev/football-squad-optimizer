# The tail-mean rank criterion, against this league's own standings

Not the pre-registered measurement. `docs/rank_tail_selector_prereg.md` registers a
147-fold paired sweep; this is the precondition that should be read before that sweep
is worth running, and it reads no development fold and scores nothing.

- Members in the capture: **15**; ordered member pairs: **210**
- Widest gap in the captured standings: **66 points**
- Band: `gap_and_weeks_strategy_rule_v1`, edge 1.0 x 21.2 x sqrt(weeks left)

## How to reproduce it

```
python -m scripts.measure_rank_tail_selector_inertness --league 352490
```

## What it establishes

Holding the captured standings fixed, **no member pair leaves the band until
gameweek 30**. A rival inside the band contributes its full mean, so on every
earlier week the criterion returns today's pick for every member at every arm. Wiring
it would change nothing for this league over that stretch, whatever the sweep says.

| Gameweek | Band edge (points) | Pairs outside the band |
| --- | --- | --- |
| 4 | 125.4 | 0 of 210 |
| 8 | 118.0 | 0 of 210 |
| 12 | 110.2 | 0 of 210 |
| 16 | 101.7 | 0 of 210 |
| 20 | 92.4 | 0 of 210 |
| 24 | 82.1 | 0 of 210 |
| 28 | 70.3 | 0 of 210 |
| 30 | 63.6 | 2 of 210 |
| 31 | 60.0 | 4 of 210 |
| 32 | 56.1 | 8 of 210 |
| 33 | 51.9 | 16 of 210 |
| 34 | 47.4 | 24 of 210 |
| 35 | 42.4 | 32 of 210 |
| 36 | 36.7 | 48 of 210 |
| 37 | 30.0 | 64 of 210 |
| 38 | 21.2 | 90 of 210 |

## The criterion's own cost

At 16 candidates, 14 rivals and 1000 scenarios, one selection takes a median **60.1 ms** over 7 repeats (minimum 59.2 ms), in the pure-Python
implementation this module ships. Fifteen members is that many times over, so the
criterion is not what would make a weekly run expensive. The design's own estimate for
this shape was 2.84 ms, so the figure to plan against is the measured one.

## Limits

- The standings are frozen at the capture while the edge shrinks with the weeks left.
  Real gaps widen over a season, so the crossing week here is an upper bound on when
  the criterion starts to bite, not a forecast of it.
- `WEEKLY_POINTS_DIFFERENTIAL_POINTS` is 21.2 from 315 pair-weeks over three
  gameweeks (`rule.py:52-63`). The inertness above is a property of that constant, and
  it is the constant this reading puts a question against, not the criterion.
- No probability, quantile or rate is computed or published here; the table is counts.
