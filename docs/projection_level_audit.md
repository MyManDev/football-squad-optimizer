# Projection level on the development folds

Contract `projection_level_audit_v1`. Protocol: `docs/projection_level_audit_prereg.md`. Stage one: descriptive, nothing fitted, nothing promoted.

Table `167f3e6aeda0` (101447 rows; not the digest `phase_c_component_evaluation` scored, see the JSON), 95914 rows read over 139 decisions from target gameweek 4, blank rows left out (0) and so are the thin-history rows the table holds no forecast for (662). Bias is realized minus forecast, so a positive bias is a forecast that ran low. Intervals resample decisions.

**By minutes a gameweek played before the decision**

| bucket | rows | forecast points | realized points | bias | 90% interval | who plays: bias | interval | when they play: bias | interval |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |
| none | 30659 | 4735 | 1023 | -0.121 | [-0.130, -0.113] | -0.059 | [-0.062, -0.057] | -0.268 | [-0.422, -0.116] |
| under_30 | 28315 | 22153 | 22837 | +0.024 | [+0.004, +0.045] | +0.036 | [+0.031, +0.041] | -0.133 | [-0.180, -0.089] |
| 30_to_60 | 17352 | 32220 | 33291 | +0.062 | [+0.032, +0.094] | +0.038 | [+0.033, +0.043] | -0.017 | [-0.058, +0.025] |
| 60_and_above | 19588 | 56199 | 58614 | +0.123 | [+0.084, +0.163] | +0.015 | [+0.010, +0.019] | +0.103 | [+0.062, +0.145] |

**By the size of the forecast**

| bucket | rows | forecast points | realized points | bias | 90% interval | who plays: bias | interval | when they play: bias | interval |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |
| under_1.0 | 56581 | 13783 | 13266 | -0.009 | [-0.018, -0.001] | -0.001 | [-0.004, +0.001] | -0.061 | [-0.106, -0.017] |
| 1.0_to_2.5 | 19868 | 36159 | 36894 | +0.037 | [+0.005, +0.068] | +0.013 | [+0.008, +0.017] | -0.007 | [-0.046, +0.033] |
| 2.5_to_4.0 | 16124 | 48689 | 48509 | -0.011 | [-0.052, +0.029] | +0.001 | [-0.003, +0.006] | -0.014 | [-0.059, +0.030] |
| 4.0_and_above | 3341 | 16677 | 17096 | +0.125 | [-0.032, +0.274] | -0.017 | [-0.026, -0.009] | +0.236 | [+0.086, +0.381] |

**Each decision's top forty per position**

| bucket | rows | forecast points | realized points | bias | 90% interval | who plays: bias | interval | when they play: bias | interval |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |
| all | 22202 | 61659 | 62908 | +0.056 | [+0.019, +0.092] | -0.003 | [-0.007, +0.001] | +0.096 | [+0.051, +0.140] |
| GK | 5547 | 8314 | 9527 | +0.219 | [+0.170, +0.266] | -0.007 | [-0.011, -0.004] | +0.472 | [+0.376, +0.571] |
| DEF | 5560 | 17112 | 16822 | -0.052 | [-0.141, +0.036] | -0.007 | [-0.014, +0.001] | -0.033 | [-0.129, +0.062] |
| MID | 5560 | 21325 | 21835 | +0.092 | [+0.009, +0.179] | -0.003 | [-0.010, +0.005] | +0.123 | [+0.041, +0.211] |
| FWD | 5535 | 14908 | 14724 | -0.033 | [-0.102, +0.036] | +0.004 | [-0.005, +0.013] | -0.016 | [-0.098, +0.069] |

## What stage two's rule says

| split | bucket | pooled bias | interval off zero | seasons with the pooled sign | opens a candidate |
| --- | --- | ---: | --- | ---: | --- |
| by_prior_minutes | none | -0.121 | yes | 4 of 4 | yes |
| by_prior_minutes | under_30 | +0.024 | yes | 4 of 4 | yes |
| by_prior_minutes | 30_to_60 | +0.062 | yes | 4 of 4 | yes |
| by_prior_minutes | 60_and_above | +0.123 | yes | 4 of 4 | yes |
| by_forecast_size | under_1.0 | -0.009 | yes | 2 of 4 | no |
| by_forecast_size | 1.0_to_2.5 | +0.037 | yes | 3 of 4 | yes |
| by_forecast_size | 2.5_to_4.0 | -0.011 | no | 2 of 4 | no |
| by_forecast_size | 4.0_and_above | +0.125 | no | 3 of 4 | no |

## 2021-22

**By minutes a gameweek played before the decision**

| bucket | rows | forecast points | realized points | bias | 90% interval | who plays: bias | interval | when they play: bias | interval |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |
| none | 6216 | 1401 | 269 | -0.182 | [-0.207, -0.157] | -0.076 | [-0.081, -0.071] | -0.345 | [-0.841, +0.070] |
| under_30 | 6279 | 5356 | 5564 | +0.033 | [-0.016, +0.089] | +0.025 | [+0.013, +0.038] | -0.079 | [-0.196, +0.046] |
| 30_to_60 | 4393 | 9090 | 9133 | +0.010 | [-0.062, +0.082] | +0.023 | [+0.012, +0.034] | -0.040 | [-0.147, +0.063] |
| 60_and_above | 4485 | 13607 | 13899 | +0.065 | [-0.029, +0.159] | +0.001 | [-0.011, +0.013] | +0.087 | [-0.009, +0.183] |

**By the size of the forecast**

| bucket | rows | forecast points | realized points | bias | 90% interval | who plays: bias | interval | when they play: bias | interval |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |
| under_1.0 | 12041 | 3753 | 3334 | -0.035 | [-0.059, -0.009] | -0.015 | [-0.021, -0.008] | -0.001 | [-0.117, +0.112] |
| 1.0_to_2.5 | 4056 | 7282 | 7800 | +0.128 | [+0.046, +0.214] | +0.019 | [+0.007, +0.031] | +0.087 | [-0.031, +0.201] |
| 2.5_to_4.0 | 4134 | 12668 | 12094 | -0.139 | [-0.218, -0.063] | -0.018 | [-0.029, -0.009] | -0.089 | [-0.186, +0.009] |
| 4.0_and_above | 1142 | 5751 | 5637 | -0.100 | [-0.420, +0.171] | -0.033 | [-0.055, -0.014] | +0.071 | [-0.217, +0.308] |

## 2022-23

**By minutes a gameweek played before the decision**

| bucket | rows | forecast points | realized points | bias | 90% interval | who plays: bias | interval | when they play: bias | interval |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |
| none | 7025 | 1067 | 253 | -0.116 | [-0.132, -0.101] | -0.058 | [-0.063, -0.052] | -0.198 | [-0.479, +0.131] |
| under_30 | 7053 | 5904 | 5975 | +0.010 | [-0.027, +0.047] | +0.039 | [+0.031, +0.047] | -0.195 | [-0.279, -0.117] |
| 30_to_60 | 3928 | 7405 | 7574 | +0.043 | [-0.014, +0.097] | +0.044 | [+0.033, +0.054] | -0.061 | [-0.133, +0.006] |
| 60_and_above | 5019 | 14649 | 15368 | +0.143 | [+0.059, +0.224] | +0.020 | [+0.011, +0.030] | +0.097 | [+0.009, +0.184] |

**By the size of the forecast**

| bucket | rows | forecast points | realized points | bias | 90% interval | who plays: bias | interval | when they play: bias | interval |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |
| under_1.0 | 13197 | 3234 | 3057 | -0.013 | [-0.030, +0.003] | +0.001 | [-0.004, +0.006] | -0.147 | [-0.239, -0.055] |
| 1.0_to_2.5 | 4805 | 8779 | 9071 | +0.061 | [-0.007, +0.124] | +0.019 | [+0.007, +0.030] | +0.008 | [-0.073, +0.086] |
| 2.5_to_4.0 | 4104 | 12440 | 12353 | -0.021 | [-0.127, +0.080] | +0.009 | [-0.002, +0.020] | -0.055 | [-0.156, +0.043] |
| 4.0_and_above | 919 | 4573 | 4689 | +0.127 | [-0.178, +0.398] | -0.001 | [-0.016, +0.013] | +0.141 | [-0.167, +0.400] |

## 2023-24

**By minutes a gameweek played before the decision**

| bucket | rows | forecast points | realized points | bias | 90% interval | who plays: bias | interval | when they play: bias | interval |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |
| none | 9640 | 1325 | 287 | -0.108 | [-0.118, -0.096] | -0.057 | [-0.061, -0.053] | -0.155 | [-0.431, +0.155] |
| under_30 | 7415 | 5438 | 5800 | +0.049 | [+0.014, +0.087] | +0.041 | [+0.032, +0.050] | -0.076 | [-0.157, +0.006] |
| 30_to_60 | 4680 | 8128 | 8747 | +0.132 | [+0.069, +0.191] | +0.039 | [+0.031, +0.046] | +0.081 | [-0.003, +0.159] |
| 60_and_above | 4889 | 13462 | 14057 | +0.122 | [+0.042, +0.204] | +0.017 | [+0.008, +0.026] | +0.097 | [+0.015, +0.181] |

**By the size of the forecast**

| bucket | rows | forecast points | realized points | bias | 90% interval | who plays: bias | interval | when they play: bias | interval |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |
| under_1.0 | 16690 | 3645 | 3674 | +0.002 | [-0.013, +0.017] | -0.002 | [-0.006, +0.003] | +0.022 | [-0.064, +0.112] |
| 1.0_to_2.5 | 5339 | 9728 | 9529 | -0.037 | [-0.087, +0.016] | +0.006 | [-0.004, +0.015] | -0.079 | [-0.142, -0.013] |
| 2.5_to_4.0 | 3937 | 11762 | 12161 | +0.101 | [+0.027, +0.171] | +0.007 | [-0.001, +0.016] | +0.091 | [+0.014, +0.169] |
| 4.0_and_above | 658 | 3219 | 3527 | +0.469 | [+0.112, +0.791] | -0.016 | [-0.032, -0.002] | +0.605 | [+0.244, +0.935] |

## 2024-25

**By minutes a gameweek played before the decision**

| bucket | rows | forecast points | realized points | bias | 90% interval | who plays: bias | interval | when they play: bias | interval |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |
| none | 7778 | 942 | 214 | -0.094 | [-0.102, -0.084] | -0.051 | [-0.056, -0.045] | -0.381 | [-0.538, -0.240] |
| under_30 | 7568 | 5454 | 5498 | +0.006 | [-0.031, +0.043] | +0.037 | [+0.028, +0.047] | -0.171 | [-0.251, -0.095] |
| 30_to_60 | 4351 | 7598 | 7837 | +0.055 | [-0.002, +0.110] | +0.046 | [+0.037, +0.056] | -0.056 | [-0.123, +0.012] |
| 60_and_above | 5195 | 14481 | 15290 | +0.156 | [+0.095, +0.217] | +0.018 | [+0.011, +0.026] | +0.129 | [+0.065, +0.195] |

**By the size of the forecast**

| bucket | rows | forecast points | realized points | bias | 90% interval | who plays: bias | interval | when they play: bias | interval |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |
| under_1.0 | 14653 | 3152 | 3201 | +0.003 | [-0.008, +0.014] | +0.007 | [+0.002, +0.013] | -0.119 | [-0.184, -0.059] |
| 1.0_to_2.5 | 5668 | 10370 | 10494 | +0.022 | [-0.020, +0.065] | +0.009 | [+0.001, +0.017] | -0.013 | [-0.072, +0.047] |
| 2.5_to_4.0 | 3949 | 11820 | 11901 | +0.021 | [-0.049, +0.090] | +0.008 | [+0.000, +0.016] | -0.003 | [-0.076, +0.067] |
| 4.0_and_above | 622 | 3135 | 3243 | +0.174 | [-0.157, +0.480] | -0.015 | [-0.029, -0.002] | +0.282 | [-0.040, +0.577] |
