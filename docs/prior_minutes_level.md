# A level correction by this season's minutes

Contract `prior_minutes_level_v1`. Protocol: `docs/prior_minutes_level_prereg.md`. Verdict: **`failed`**.

## Gate 1: level, out of sample

| prior minutes a gameweek | rows | bias as it stands | bias corrected | passes |
| --- | ---: | ---: | ---: | --- |
| none | 29065 | -0.121 | -0.007 | yes |
| under_30 | 27196 | +0.013 | -0.038 | no |
| 30_to_60 | 16566 | +0.066 | +0.024 | yes |
| 60_and_above | 18223 | +0.136 | +0.045 | yes |

Points MAE 1.0795 as it stands, 1.0607 corrected. Gate 1 fails.

## Gate 2: realized squad points, candidate minus the forecast as it stands

Mean -0.218 a gameweek over 147 decisions, 90% block bootstrap interval [-0.830, +0.313]; wins/ties/losses 21/107/19; 51 decisions chose a different squad.

| season | mean difference |
| --- | ---: |
| 2021-22 | -1.189 |
| 2022-23 | +1.139 |
| 2023-24 | +0.000 |
| 2024-25 | -0.784 |

| arm | mean realized | proven optimal | starters with zero minutes |
| --- | ---: | ---: | ---: |
| as_it_stands | 63.415 | 0.72 | 83 |
| corrected | 63.197 | 0.73 | 83 |

## The factors at the last decision

- none: 0.217 (from 138 earlier decisions)
- under_30: 1.029 (from 138 earlier decisions)
- 30_to_60: 1.033 (from 138 earlier decisions)
- 60_and_above: 1.043 (from 138 earlier decisions)
