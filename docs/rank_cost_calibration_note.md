# The rank objective's cost side is not the defect. Its target might be.

This measurement was run to establish a baseline before fixing a believed defect: that the
rank objective's *expected* cost in points understated its *realized* cost, remembered as
about +1 expected against +3 realized. The fix was scheduled work.

**The defect does not reproduce, and the gate said so before the numbers existed.** The
pre-registered condition was: the mean realized cost must fall *outside* the 90% interval of
the mean expected cost, otherwise there is no defect and the scheduled fix is cancelled.

## What the cost side actually does

2024-25, 37 folds, 100 scenarios each, `held_out_half` claim scenarios, rival = the fold's own
risk-neutral squad. Cost is the template's score minus mine, expected on the scenarios and
realized on what happened; the gap is bootstrapped over folds.

| Budget | Expected cost | Realized cost | Gap | 90% interval | Excludes zero |
| ---: | ---: | ---: | ---: | --- | --- |
| 0 | +1.508 | +1.757 | +0.249 | [−1.806, +2.366] | no |
| 2 | +1.447 | +2.486 | +1.039 | [−1.372, +3.468] | no |
| 4 | +1.319 | +1.108 | −0.211 | [−2.239, +1.889] | no |
| none | +1.082 | +0.108 | −0.974 | [−2.739, +0.848] | no |
| **pooled** | **+1.339** | **+1.365** | **+0.026** | **[−1.022, +1.091]** | **no** |

The gap does not even run consistently in one direction: two budgets over-realize and two
under-realize. Pooled it is +0.026 points on a cost of about +1.34.

**Item (a) is cancelled.** It was scoped as "fix the cost side"; there is nothing measurable
to fix.

## Two limits, stated rather than used as an escape

- **Power.** Thirty-seven folds give intervals about two points wide. This rules out a *large*
  systematic gap, not a small one. "No measurable defect" is not "no defect".
- **Solver status.** Only budget 0 is mostly proven optimal (30 of 37); budget 4 is 1 of 37 and
  the unbounded budget is 0 of 37 — the rest hit the thirty-second limit and returned whatever
  they had found. So the two rows with the largest negative gaps are the least trustworthy.
  This does not rescue the cancelled item: the best-proven row shows no miscalibration either.
- The remembered "+1 expected against +3 realized" is not reproduced here and its origin could
  not be located. It is not being chased.

## What the run found instead, and it is larger

The claim side is honest — that fix already worked:

| Budget | Claimed | Realized | In-sample |
| ---: | ---: | ---: | ---: |
| 0 | 0.35 | 0.38 | 0.52 |
| 2 | 0.44 | 0.41 | 0.60 |
| 4 | 0.42 | 0.35 | 0.57 |
| none | 0.43 | 0.38 | 0.57 |

Claimed tracks realized within a few points, while the in-sample share sits 15–20 points
higher. `held_out_half` is doing exactly what it was built for.

But look at where those probabilities sit:

| Budget | Ahead | Level | **Behind** |
| ---: | ---: | ---: | ---: |
| 0 | 0.38 | 0.16 | **0.46** |
| 2 | 0.41 | 0.08 | **0.51** |
| 4 | 0.35 | 0.16 | **0.49** |
| none | 0.38 | 0.22 | **0.41** |

**The rank objective finishes behind more often than ahead, at every budget** — against a
rival that is the risk-neutral squad, which sits inside its own feasible set. Copying the
rival exactly would guarantee a level finish. It declines to, and pays about 1.3 points a
gameweek for the privilege.

That is not a bug. `optimize_rank_probability_squad` maximises the probability of being
*strictly ahead*, and under that objective a tie is worth exactly zero, so trading a certain
tie for a 38% win and a 46% loss is correct arithmetic. The question it raises is whether the
target is the one anyone wants.

## What this changes

The scheduled work assumed the objective was right and its accounting was wrong. It is the
other way round: the accounting is honest and the target is worth arguing about.

Three candidate targets, none of them measured yet:

- **P(strictly ahead)** — today's. Correct when only first place counts and a tie is a loss.
- **P(not behind)** — treats a level finish as a success. A manager defending a lead wants
  this one, and it is a one-line change to the same solver.
- **Expected rank** against several rivals — the only one that means anything in a mini-league
  of more than two, and the one with no machinery at all.

Measuring the first two against each other costs about what this run cost, reuses the same
rehearsal, and gates everything downstream: windowing an objective (item b) and choosing plans
with it (item d) are both building on whichever target turns out to be right.
