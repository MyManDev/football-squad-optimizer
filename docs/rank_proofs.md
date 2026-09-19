# The rank solve, at the solver default and at the window level

Contract `rank_proofs_v1`. Season 2024-25, origins [8, 14, 20, 26, 32], horizons [1, 3, 5], 100 scenarios at seed 11. Both arms are the cells `windowed_rank` measures, built by that runner's own setup: same folds, pool, rival, seed and budget. Only CP-SAT's linearization level differs. Descriptive: nothing is promoted and no default moves.

| horizon | arm | solves | proved | largest open relative gap | wall seconds |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | `solver_default` | 5 | 0 | 3.7143 | 46 |
| 1 | `window_level` | 5 | 0 | 13.0000 | 44 |
| 3 | `solver_default` | 5 | 0 | 99.0000 | 44 |
| 3 | `window_level` | 5 | 0 | 32.0000 | 45 |
| 5 | `solver_default` | 5 | 2 | 32.3333 | 35 |
| 5 | `window_level` | 5 | 0 | 100.0000 | 41 |

## What the objective phase actually held

2 of 30 solves are proved. In every one of the 28 that are not, the bound on the ahead count sits between 98 and 100 of 100: the solver never rules anything out, so the bound says nothing.

The first phase is the one that maximizes the ahead count, and it is not searching. Across the 30 cells it stops holding a squad that is ahead in a median of 31 scenarios, as few as 0 and as many as 100; in 11 of 30 cells it holds fewer than ten of 100. What the record finally reports is the ahead count of the squad the later phases arrive at, which is a different squad.

## Where the two arms chose differently

In 14 of the 15 cells the two arms chose a different eleven or a different captain. The default's squad is ahead in more scenarios in 11 of them, and the widest difference between the two is 66 scenarios of 100.

**That is the reading, and it is not about the lever.** The two arms differ by one CP-SAT parameter, which cannot change where the optimum is. It changes the reported answer by up to 66 of 100. So the number this model reports is a property of where the search happened to stop, not of the objective, and `windowed_rank`'s published claims are one such stopping point among many. The lever does not rescue that: it mostly makes the stopping point worse, which is a smaller fact than the one above and would be the wrong thing to take from this.

- horizon 1, origin 8: ahead count 51 at the default against 19 at the window level.
- horizon 1, origin 14: ahead count 40 at the default against 49 at the window level.
- horizon 1, origin 20: ahead count 92 at the default against 66 at the window level.
- horizon 1, origin 26: ahead count 37 at the default against 39 at the window level.
- horizon 1, origin 32: ahead count 86 at the default against 62 at the window level.
- horizon 3, origin 8: ahead count 87 at the default against 31 at the window level.
- horizon 3, origin 14: ahead count 100 at the default against 35 at the window level.
- horizon 3, origin 20: ahead count 97 at the default against 86 at the window level.
- horizon 3, origin 26: ahead count 31 at the default against 12 at the window level.
- horizon 3, origin 32: ahead count 99 at the default against 62 at the window level.
- horizon 5, origin 8: ahead count 62 at the default against 95 at the window level.
- horizon 5, origin 20: ahead count 100 at the default against 34 at the window level.
- horizon 5, origin 26: ahead count 98 at the default against 44 at the window level.
- horizon 5, origin 32: ahead count 100 at the default against 73 at the window level.
