# What the team rating earns, and the clause it fails on

`team_rating_study.md` is stage two of the recommender programme. Its headline is that the
rating **does not clear its gate**, and the shape of that failure matters more than the
headline, because two of the three clauses pass decisively and the third fails on two ties.

## The three clauses

| Clause | Result |
| --- | --- |
| **Goals** — beat a constant-rate baseline at predicting scorelines, every season, interval clear of zero | **passes**: +0.1020 log-likelihood per fixture [+0.0756, +0.1323]; +0.071 / +0.131 / +0.104 by season |
| **Clean sheets** — better calibrated than a logistic on the published rating, pooled *and* in all but at most one season | **fails**: pooled +0.0035 Brier [+0.0006, +0.0062], but better in only **1 of 3** seasons |
| **Players** — order player points at least as well as the published rating, both sides of the ball | **passes**: attacking +0.0631 against +0.0213, defensive +0.0674 against +0.0473 |

The clean-sheet clause fails on consistency, not on defeat. The season that wins wins by a
lot (2023-24, +0.0113 Brier) and the two that lose lose by almost nothing (−0.00063 and
−0.00029, on a Brier of about 0.17 — a quarter of a percent). Pooled, the interval clears
zero in the rating's favour. The declared bar asked for the sign to hold across seasons and
it does not, so the verdict is a fail, and the bar is not being moved after the fact.

## What passed is the part stage three needs

The reason the players clause matters more than its position in the list suggests: it is the
only clause measured against the thing an opponent-aware projection actually consumes. The
rating orders attackers' points **three times** as well as the published difficulty rating
does (+0.063 against +0.021), and better on the defensive side too. That is the increment
the schedule signal study could not find with a blunt instrument, and it is the reason
stage three is worth running at all.

It should also be read for what it is: a Spearman correlation of 0.06 between a fixture
signal and a player's weekly points is a *small* effect measured over a population that
includes every unused substitute. Both instruments are small; one is three times the other.

## Where the rating is well calibrated, and where it is not

The reliability table is the honest picture of the clean-sheet result:

| Predicted band | Rows | Predicted | Realized |
| --- | ---: | ---: | ---: |
| 0.0–0.1 | 179 | 0.071 | 0.084 |
| 0.1–0.2 | 565 | 0.154 | 0.172 |
| 0.2–0.3 | 623 | 0.249 | 0.244 |
| 0.3–0.4 | 394 | 0.343 | 0.325 |
| 0.4–0.5 | 181 | 0.438 | 0.392 |
| 0.5–0.6 | 40 | 0.534 | 0.325 |

Calibration is good through the middle, where most fixtures sit, and breaks in the top band:
in the 40 fixtures where the rating promised better than an even chance of a clean sheet, it
happened a third of the time. Those are exactly the fixtures a defender is bought for. That
band is the single most useful thing this study found for stage three, and it argues for
using the *probability* rather than a rescaled multiplier — and for capping what the top of
the distribution is allowed to claim.

## How the model was chosen, in the order it happened

Recording this because the sequence, not just the result, is what makes a measurement
trustworthy:

1. The estimator was written with hard-coded constants (180-day half life, ridge 2.0) and
   run once on 2024-25 as a smoke test. That run is exploratory, not evidence.
2. Hard-coded constants make a rating's showing partly a matter of taste, so the half life
   and ridge became a grid **selected per judged season on the seasons before it**. Selected
   values: 500 days / ridge 2.0 for 2022-23, 180 days / ridge 5.0 for the other two.
3. Two fairness corrections followed, both made before the formal run and both because the
   comparison was not like-for-like:
   - the attacking signal became the rating's **expected goals for the player's club in that
     fixture** rather than the opponent's defence alone, because the published rating scores
     a *fixture* and already folds in the venue;
   - the rating's clean-sheet probability was given the **same fitted logistic recalibration**
     the published baseline gets, walked forward on earlier seasons. A goal model's clean
     sheet probability is a by-product; comparing an uncalibrated by-product against a fitted
     logistic would measure the fitting rather than the rating.
4. The formal run was then made once, and the verdict is what it produced.

The recalibration is monotone, so it cannot change any ordering: the players clause is
identical with or without it. It moved the Brier by 0.0001.

## Limits

- **Goals only.** The rating knows scorelines, not shots, not expected goals, not whether a
  club was down to ten men. A better-informed rating would very likely calibrate its top
  band better, which is where this one breaks.
- **No squad news.** A club whose first-choice striker is injured carries the same attack
  rating as one at full strength. Over a season the decay handles it slowly; over one
  gameweek it does not handle it at all.
- **Judged from gameweek 6.** The opening of a season, where the promoted prior does the
  most work and a rating would be worth the most, is not judged here. The prior is measured
  and tested but its value at gameweek 1 is not.
- **The player clauses pool every row**, including players who did not appear. Both
  instruments are handicapped identically, so the comparison stands, but the absolute
  numbers are not a claim about how much fixture difficulty explains a player's week.

## What happens next

Stage three (`opponent_projection`) measures the rating inside a projection anyway, as a
measurement, with no promotion available to it: the gate above did not pass, and
`prediction/` belongs to the data side regardless. What stage three tests is precisely the
thing the schedule signal study showed cannot be assumed — whether a better ordering of
fixtures survives to the decision, or dies on the way there like the published rating did.
