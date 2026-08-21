# The opening prior is mis-levelled, and price is still the best ranker

Artifacts: `opening_newcomer_study.{json,md}` (contract `opening_newcomer_study_v1`).
Runner: `scripts.run_opening_newcomer_study`. Walk-forward over the development seasons,
judged on 2022-23, 2023-24 and 2024-25; the locked 2025-26 holdout was not read; nothing
was promoted.

## Why the study exists

On the real 2026-27 opening capture, **199 of 587 players had no prior record** — signings
from abroad, promoted clubs' squads, academy graduates — and every one of them was
projected by a single line through the origin, `0.29941 x price in millions`. A £15m
signing and a £15m squad player receive the same expectation, while the deadline publishes
how much of the field has already picked each player, the game's own expected points, and
who each club plays first. Human managers use exactly those signals. The question was
whether the model should.

## What the population looks like

| Season | Opening rows | Newcomers | Share | Movers | Newcomers who did not play |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021-22 | 554 | 218 | 39% | 18 | 67% |
| 2022-23 | 573 | 202 | 35% | 27 | 64% |
| 2023-24 | 658 | 253 | 38% | 31 | 72% |
| 2024-25 | 616 | 201 | 33% | 39 | 72% |

Two thirds of newcomers **do not appear at all** in the opening gameweek. That single fact
explains most of what follows.

## Finding 1: the shipped prior is roughly twice too high for newcomers

Over 874 newcomer rows it predicts **1.387** points where **0.686** were scored — a bias of
**+0.701** and a mean absolute error of 1.364. The coefficient is not wrong; it was fitted
on *every* opening player, and most of those have a record and play. Applied to a
population that mostly does not play, it over-predicts by about a factor of two.

Refitting the same shape on newcomers only — `M1`, one price coefficient per position —
removes most of it: mean absolute error 1.364 → **0.97 pooled** (+0.333, 90% interval
[+0.307, +0.355]), and the per-season bias falls from +0.54/+0.84/+0.90 to
+0.09/+0.40/+0.32.

## Finding 2: ownership and the game's expectation improve the level, not the order

Adding ownership (`M2`) and the game's own xP (`M3`) improves accuracy further
(**+0.363** and **+0.401** pooled, both intervals well clear of zero) — but the **ordering
gets worse in every season**. Within position, Spearman against realized points:

| | 2022-23 | 2023-24 | 2024-25 |
| --- | ---: | ---: | ---: |
| control (price) | 0.515 | 0.471 | 0.511 |
| `M2` ownership | 0.483 | 0.364 | 0.433 |
| `M3` + the game's xP | 0.363 | 0.320 | 0.352 |

Restricting the comparison to newcomers who actually played (a diagnostic, not part of the
gate) says the same: 0.169/0.220/0.293 for price against 0.116/0.123/0.123 for `M3`. Price
is the better ranker; ownership and xP mostly tell you *whether he will play at all*, which
the level already needed and the ordering does not reward.

Adding the opening fixture on top (`M4a` published difficulty, `M4b` our own carried club
strength) changes little: +0.394 and +0.389 pooled, ordering worse again. For an opening
week the fixture is not what separates these players.

## Finding 3: the decision gains come from a handful of crowd-known signings

The squad the optimizer builds from `M3` scores **+12 / +0 / +7** realized points against
the control's, never worse, mean **+6.3**. The mechanism is visible and specific: in
2022-23 the candidate starts two newcomers the control cannot see, one of them Erling
Haaland — £11.5m, 56% owned, the game's own xP 5.0, 13 points scored. The control's price
line put him behind established players; ownership and xP moved him past them.

That is the user's intuition confirmed — and it is a *level* effect, not an ordering one.

## Finding 4: movers are over-predicted, but not stably enough to correct

115 players changed clubs across the studied openings. Their carried projection is biased
**−0.512** against **−0.332** for players who stayed, but the per-season sign is not stable
(−1.326, −0.652, **+0.239**, −0.635). The best shrink toward the price prior is 0.00 — that
is, ignore the carried rate entirely — which lowers mean error (1.425 against 1.577) but
**does not improve every evaluated season**. On 115 rows across four seasons that is not
evidence, and no mover correction is proposed.

## The verdict, by the gate fixed before the numbers

| Candidate | Accuracy | Ordering | Decision | Passes |
| --- | --- | --- | --- | --- |
| `M1` price by position | pass | fail | pass (+0.0, 0 losses) | no |
| `M2` ownership | pass | fail | pass (+4.0, 0 losses) | no |
| `M3` + the game's xP | pass | fail | pass (+6.3, 0 losses) | no |
| `M4a` published difficulty | pass | fail | pass (+2.7, 0 losses) | no |
| `M4b` carried club strength | pass | fail | pass (+2.7, 0 losses) | no |

**Nothing is promoted.** The opening gameweek runs on the control.

The ordering criterion is what blocks it, and one nuance matters for whoever reads this
next: `M1` does not make the ordering *worse* — within a position it is a positive multiple
of price, so its ordering is identical to the control's to three decimals. The
pre-registered wording asked for a strict improvement, and identical is not an improvement.
That wording will not be relaxed after seeing the numbers; it will be restated, before the
next run, as "does not worsen".

## What the next study should ask

The data has already named its own next model. Two thirds of newcomers do not play, and
ownership is the signal that separates those who will from those who will not, while price
orders the ones who do. So the shape to test is **two-part**:

    expected points = P(plays | ownership, price) x points if he plays (price, position)

with the ordering criterion restated as "does not worsen", and both parts fitted
walk-forward exactly as here. If that clears the bar it fixes the level *and* keeps the
ordering, which is the only combination this study found missing.

Beside it, two smaller items: the mover question deserves more rows than four seasons of
openings give it (the same shrink measured across every gameweek of a season, not just the
first), and club strength belongs to the in-season projection, where the residuals already
show it unspent (+0.162 attacking, +0.322 defensive, issue #88), rather than to the opening
week where this study found it inert.
