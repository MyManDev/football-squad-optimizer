# Joint role and minutes development measurement

Measured on 2 October 2026 at source commit
`272f12682c2996eb0324b44186ff4adecedb8550`. The joint model improves average
minute error in this development comparison. Point-error changes are small,
and several component and position results worsen. This is not a model
promotion or evidence of realized FPL points gained.

## Comparison and population

The control is `football_team_share_v1`; the candidate is
`football_joint_role_minutes_v1`. This does **not** compare against the separate
Phase C baseline. Each origin fits the candidate once and evaluates the old
football prediction path using the shared fitted heads, with no additional
control fit. Appearance probability therefore remains identical.

All 13 preregistered origins completed; there were no failed folds. Eight
historical origins cover GW11, GW19, GW27 and GW35 in each of 2023-24 and 2024-25.
Five further origins cover the captured, settled 2026-27 GW1-5. The historical
targets contain 6,228 player-fixture rows and the current targets 3,191, for
9,419 total. Results below average origins equally, rather than pooling rows.
DEFCON has only five current-season origins and 2,840 labelled outfield rows;
historical missing labels were not filled with zero.

2022-23 supplies prior history only. Supervised training uses earlier eligible
2023-24/2024-25 rows and, for current origins, earlier captured 2026-27 weeks.
Role training uses appearances with recorded binary starts, never roles inferred
from minutes. Shrinkage remains 10 prior rows, logistic `C=1`, seed 0; there was
no hyperparameter search, availability backfill or news backfill.

## Paired results

Lower loss is better. Better/worse counts refer to the candidate across paired
origins, not players. MAE is mean absolute error; Brier and NLL assess
probability forecasts.

| Metric | Control | Joint role | Joint minus control | Better / worse |
| --- | ---: | ---: | ---: | ---: |
| Minutes MAE | 15.031295 | 14.669032 | -0.362263 | 13 / 0 |
| Minutes MSE | 599.461764 | 595.456146 | -4.005618 | 10 / 3 |
| 60-minute Brier | 0.099209 | 0.098790 | -0.000419 | 9 / 4 |
| Minute-bin NLL | 0.741836 | 0.740043 | -0.001794 | 8 / 5 |
| Minute-bin Brier | 0.378202 | 0.378045 | -0.000157 | 4 / 9 |
| Points MAE | 1.074450 | 1.070099 | -0.004351 | 10 / 3 |
| Points MSE | 4.150199 | 4.147696 | -0.002502 | 6 / 7 |
| Goals MAE | 0.068793 | 0.068569 | -0.000224 | 13 / 0 |
| Assists MAE | 0.066478 | 0.066352 | -0.000126 | 12 / 1 |
| Clean-sheet Brier | 0.067077 | 0.067168 | +0.000091 | 7 / 6 |
| DEFCON Brier | 0.048959 | 0.048966 | +0.000007 | 2 / 2; 1 tie |

Minutes MAE falls about 2.41%, but the mean signed minutes bias becomes more
negative: -1.2040 to -1.5038 minutes. The 60-minute bias likewise changes from
-0.01040 to -0.01497. Appearance Brier is unchanged at 0.117036. Goals and
assists Poisson NLL improve slightly overall, while their MSEs increase by
0.00000927 and 0.00001500 respectively.

The aggregate hides position differences. Goalkeeper minutes and points MAE
worsen in 12 of 13 origins. Defender points MAE worsens in 10 of 13. Midfielder
and forward points MAE improve in 11 and 13 origins respectively. The mean
minute-bin Brier improves despite worsening in nine origins; points MSE has
the same mixed pattern, improving on average but worsening in seven origins.

## Current-season slice and role scores

Across the five current origins, minutes MAE changes from 17.254255 to 16.930400,
60-minute Brier from 0.121773 to 0.120754, and points MAE from 1.273045 to
1.266420. However, goals Poisson NLL worsens by 0.00006501, assists Poisson NLL
by 0.00038917 and clean-sheet Brier by 0.00021880. Current-season evidence is
therefore mixed too.

All 9,419 target rows have a scored role label. Candidate role NLL/Brier are
0.564326/0.300226 overall and 0.750458/0.386878 in the current slice. The old
control has no start/cameo distribution, so its role metrics and paired role
deltas are null. These numbers do not establish improved role calibration.
Current GW1 is particularly weak, with role NLL 1.584764; the receipt alone
does not establish its cause.

## Evidence limits and execution

This is retrospective development evidence. Historical fixtures and player
populations are reconstructed, not archived deadline rosters. Current history
uses the captured roster and can omit former or transferred players. The
90-minute deadline and three-hour settlement rules are proxies, not verified
historical publication times. The points residual remains fixed per appearance
instead of being decomposed into minute-specific events. No optimizer outcome,
realized squad gain, independent superiority or prospective calibration was
measured.

The receipts record 13 candidate fits, 118.44 seconds total including 50.39
seconds preparation, unchanged source, twelve explicitly allowed archive files,
no excluded-season access, no provider calls and no live changes. The protocol
has no promotion rule and the final result records `promotion: false`.
The evidence set is `protocol.json`, `folds.json`, `scores.json`,
`comparison.json`, `budgets.json`, `failures.json`, `result.json`,
`current-evidence.json` and the source/input/operator receipts from
`current100-measure01`.
