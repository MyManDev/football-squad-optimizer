# Anchored calibration: the decomposed claim against what happened

- Rows: 1064; identity max gap 0.0000 (passes at 0.02).
- Shadow-infeasible folds: 40.

| cell | n | claimed | realized | gap | 90% CI | dist. from degenerate | clause |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| h1:risk_neutral | 139 | 0.332 | 0.345 | -0.013 | [-0.079, +0.055] | 0.000 | passes |
| h1:contrarian | 139 | 0.249 | 0.252 | -0.003 | [-0.064, +0.057] | 0.094 | passes |
| h1:shadow | 99 | 0.264 | 0.354 | -0.090 | [-0.170, -0.013] | 0.079 | fails |
| h3:risk_neutral | 131 | 0.300 | 0.321 | -0.021 | [-0.089, +0.045] | 0.000 | passes |
| h3:contrarian | 131 | 0.128 | 0.145 | -0.017 | [-0.068, +0.030] | 0.172 | passes |
| h3:shadow | 93 | 0.163 | 0.312 | -0.149 | [-0.228, -0.074] | 0.135 | fails |
| h5:risk_neutral | 123 | 0.246 | 0.293 | -0.047 | [-0.112, +0.022] | 0.000 | passes |
| h5:contrarian | 123 | 0.072 | 0.081 | -0.010 | [-0.052, +0.030] | 0.174 | passes |
| h5:shadow | 86 | 0.115 | 0.256 | -0.141 | [-0.217, -0.067] | 0.132 | fails |

**Verdict: fails** (identity ok, calibration FAILED, ordering ok).

- Measurement only; the locked 2025-26 holdout is refused by the development season list.
