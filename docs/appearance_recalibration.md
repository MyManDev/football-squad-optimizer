# Appearance recalibration

Verdict **fails** under `appearance_recalibration_v1`. Ranking: fails; error: passes; decisions: fails.

Same-row Brier: 0.1073406211310611 before, 0.10478270204354007 after. Historical reference 0.10734 is not substituted for this paired base.

Paired decisions: 147; mean candidate minus base 0.3469387755102041; 90% interval (-0.6265306122448984, 1.3136054421768701); complete for gate: True.

The [JSON twin](appearance_recalibration.json) retains seasonal/positional readings, reliability bins, training counts, solver statuses and input/declaration identities. See [the frozen declaration](appearance_recalibration_prereg.md).

Historical 2021-25 scoring has no DEFCON. This does not establish live DEFCON performance or top-100 ability and does not promote an operational model.

## Same-row probability and full-roster point readings

All pairs below are base / candidate. Brier uses eligible component rows; MAE and nonplayer forecast mass use the full roster, including fallbacks and blanks.

| Season | Brier | Point MAE | Nonplayer forecast mass |
| --- | --- | --- | --- |
| 2021-22 | 0.118716 / 0.116902 | 1.253980 / 1.227610 | 0.244716 / 0.234671 |
| 2022-23 | 0.105923 / 0.103861 | 1.114135 / 1.088945 | 0.200143 / 0.187755 |
| 2023-24 | 0.102134 / 0.099075 | 0.994770 / 0.969787 | 0.218563 / 0.203249 |
| 2024-25 | 0.104657 / 0.101550 | 1.022453 / 1.003762 | 0.193876 / 0.183832 |
| pooled | 0.107341 / 0.104783 | 1.088578 / 1.064867 | 0.214525 / 0.202519 |

## Pooled within-position ranking

| Position | Rows | Base Spearman | Candidate Spearman |
| --- | ---: | ---: | ---: |
| GK | 11145 | 0.668026 | 0.673264 |
| DEF | 34039 | 0.601298 | 0.605583 |
| MID | 43826 | 0.715392 | 0.716983 |
| FWD | 12437 | 0.709400 | 0.708805 |

## Paired decisions by season

Descriptive means below are not binding when the complete-pair/clock-stop check fails.

| Season | Candidate minus base |
| --- | ---: |
| 2021-22 | -0.189189 |
| 2022-23 | 0.777778 |
| 2023-24 | 2.000000 |
| 2024-25 | -1.189189 |
