# Composing the control through the conditional start probability

Contract `participation_composition_v1`. **Descriptive.** Nothing is promoted, no threshold moves, no gate is stated, the operational control is unchanged and the locked 2025-26 holdout was not read.

## Why there is no gate here

`START_TARGET_SUPPORTED_SEASONS` declares the archive's `starts` label over 2023-24 and 2024-25 and no other season. 2022-23 carries the column and not its values, summing to zero over GW1-GW15 beside normal minutes, and `src/squadopt/data/cleaning.py` refuses a partly populated canonical column ("complete, so supply the values or drop the column"), so the season goes whole. 2025-26 carries the column and is the locked holdout. Two declared seasons, one spent on the fit, leaves one judged season. A threshold written over one season is a threshold one season of noise can clear, so this record states none and asks to be read as a description.

## The three arms

All three are fitted on 2023-24 and read on 2024-25, share one appearance model, and differ only in the points side.

```text
uncomposed  = p_appearance * E[points | appearance]
state_split = p_appearance * (c * E[points | start] + (1 - c) * E[points | substitute])
composed    = p_appearance * (q * E[points | start] + (1 - q) * E[points | substitute])
```

`c` is the training season's own start rate among appeared rows, 0.7379, so `state_split` knows that the two states score differently and knows nothing about which player is which. `q` is `participation_conditional_start_v1`, fitted on 10746 appeared and labelled rows. The state points models are the control's own ridge over 7930 started and 2816 substitute rows against the pooled fit's 10746.

## Points error

26303 rows of the judged season, 11124 of them appearances. Both populations are reported together because the majority never appears and an all-rows number is mostly a reading of those rows. A realized value is `points_target` on an appearance and zero elsewhere; error is forecast minus realized, so a positive number is over-forecasting. Of those rows, 168 carry no fitted forecast in any arm, which is the whole of the difference between this count and the 26135 the arms actually differ on below.

| arm | all rows: mean error | all rows: MAE | appeared rows: mean error | appeared rows: MAE |
| --- | ---: | ---: | ---: | ---: |
| `uncomposed` | +0.0110 | 1.0303 | -0.4926 | 1.9096 |
| `state_split` | +0.0032 | 1.0494 | -0.5900 | 1.8757 |
| `composed` | +0.0144 | 1.0305 | -0.4877 | 1.9070 |

By realized state, mean error:

| arm | absent: mean error | substitute: mean error | start: mean error |
| --- | ---: | ---: | ---: |
| `uncomposed` | +0.3822 | +0.1444 | -0.7344 |
| `state_split` | +0.4403 | +0.3284 | -0.9385 |
| `composed` | +0.3845 | +0.1328 | -0.7232 |

`q` is present on 26135 rows, and `composed` differs from `uncomposed` on 26135. 168 rows carry no fitted forecast in any arm and fall back identically in all three.

## Decisions

| arm | decisions | mean realized points | proved optimal |
| --- | ---: | ---: | ---: |
| `uncomposed` | 37 | 65.297 | 19 of 37 |
| `state_split` | 37 | 61.865 | 4 of 37 |
| `composed` | 37 | 63.892 | 18 of 37 |

Paired against `uncomposed`, decision by decision:

| arm | decisions | mean difference | interval | W/T/L | different squad |
| --- | ---: | ---: | --- | ---: | ---: |
| `state_split` | 37 | -3.432 | [-6.649, -1.539] | 14/6/17 | 36 |
| `composed` | 37 | -1.405 | [-3.569, +0.164] | 9/14/14 | 26 |

The interval is a moving-block bootstrap over the weeks of one season. It describes how much these 37 weeks move; it cannot describe how much the next season would.

`state_split`'s interval excludes zero, so its loss of -3.432 a decision reads as one at this level, over 37 decisions of a single season.
**No loss or gain is claimed for `composed`.** Its difference is -1.405 a decision and its interval covers zero, so these 37 decisions cannot separate it from nothing.

What the weeks do establish about `composed` is that it changed most of the squads while changing the error in the fourth decimal. A change that buys nothing on the error and is not a rounding difference on the squads is refusable on those grounds without a loss, and claiming one it cannot support would only give the first reader who checks the interval a reason to discount the rest.

**A candidate can be indistinguishable on the error and substantially different in what it does**, and this record is not a caution about that happening to somebody else. It happened here, to the arm that looked best: `state_split` has the best appeared-row mean absolute error of the three and the worst decisions, and it is the only arm whose interval excludes zero. An accuracy reading alone would have ranked it first.

## What would make this a gate, and when

The second judged season is the **live 2026-27 season**, not the locked 2025-26 holdout, which stays locked: nothing here loads it, lists it or hashes it, and reading it early would spend the one season that could confirm this one. After gameweek 9 the live record can offer the weeks it has settled by then, and the same three arms are read on them. The label there is **not** the archive's `starts`. `docs/rotation_evidence_prereg.md` declares the prospective source as a settled capture's `stats.starts > 0` and admits a gameweek only once its `rotation_evidence_v1` artifact and its settled outcome are both on disk. That dependency is the plan's first step rather than an assumption behind it: no such artifact exists under `data/` today, checked by listing rather than taken on trust, so the follow-up begins by establishing whether the weeks it needs carry one, and reports that it does not rather than quietly reading a shorter population. Only with a second judged season in hand is it worth asking whether a gate is worth writing, and that gate would be pre-registered before the run and never after it.

## What else was running

Another session's parallel `pytest -n 2` run was on this machine while these solves ran, and a third session holds the live backend. Both solver limits are deterministic, so no number in this record moves under that load; `elapsed_seconds` does, and is not a quiet-machine timing.

