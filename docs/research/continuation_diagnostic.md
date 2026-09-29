# A small ANN for recorded continuation returns

Measured 29 September 2026, under the [prespecified protocol](continuation_diagnostic_protocol.md).
This is a development diagnostic on the old historical runner, not a test of the
current football forecast or a learned planner policy. The mathematical boundary is
described in [state and learning](planner_state_and_learning.md).

The input audit found 24 files, 80 chains and 2940 decisions. These compressed
records omit complete purchase lots, exact XI/captain actions and publication times
for modern forecasts/news. We do not manufacture those fields. Six recorded
decision-time features predict the next three or five calendar weeks' mean realized
net points under the recorded policy. Missing calendar weeks are excluded.

Train on 2021-22/2022-23, select on 2023-24, then evaluate on already-consumed
2024-25 development data. All policy variants for a deadline stay together and their
combined sample weight is one deadline. The 3-week partitions have 1280/680/680
rows; five weeks have 1160/640/640. The final partitions contain only 34 and 32
distinct deadlines respectively, with overlapping outcomes, not hundreds of
independent matches. No previously unused holdout was opened.

| Model | 3-week target MAE | 5-week target MAE |
| --- | ---: | ---: |
| Training mean | 12.5897 | 11.2260 |
| Ridge | 13.5600 | 12.2338 |
| Small boosted tree | 15.5745 | 13.1172 |
| Selected ANN, seed 0 | 15.2997 | 12.5628 |
| Same ANN, seed 1 | 14.8244 | 12.4176 |
| Same ANN, seed 2 | 14.9926 | 13.4887 |

Lower is better. These are errors in mean net points per future week, not points
won by following a plan. Selection chose 16 hidden units with alpha=1 for three
weeks and alpha=10 for five. All six final ANN fits reached the declared 500
iteration limit; this nonconvergence is recorded, not repaired by tuning on the
evaluation season. It limits what can be concluded about neural networks in general.
All models fell back on seven final rows per window outside the training feature
range. Nonfinite observations/predictions also return the training mean.

The machine-readable record includes all four selection trials, three final seeds,
RMSE, convergence warnings, source/input hashes and deadline-grouped five-week
moving-block 95% intervals for MAE difference versus the constant. None supports a
positive development MAE gain. One season and selected overlapping policy chains
are not a basis for a population-level policy superiority claim.

**Decision:** no ANN value is connected to the optimizer. The coarse representation
did not pass even its prediction diagnostic, and no decision-quality comparison
or prospective promotion gate passed. Adding IQL/CQL would not recover the omitted
state/action information. Richer timestamped football/decision observations are
needed before a policy experiment; this result does not say neural networks cannot
help with those richer inputs. The earlier negative GP remains separately recorded.

Reproduce with `python -m scripts.measure_continuation_diagnostic --artifacts
<historical-artifact-root> --output <fresh-directory>` using the recorded hashes and
an existing sklearn version supporting weighted MLP fitting. No package is installed
by the runner and no production dataset is written. Seven targeted tests cover
future-only target construction, missing-week refusal, policy-clone weights,
chronological selection, finite training and unknown-observation fallback.
