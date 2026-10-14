# Experimental club form for football decisions

The owner's 9 October 2026 request adds current team results and defensive form to a
separately selected football candidate. Refs #1051; combined one-week automatic
substitution selection also needs #1049 merged. Neither implementation promotes a
model, runs a real forecast or changes the weekly publisher.

## Existing context and research

The accepted fixture model already uses the last ten available club matches' goals
for/against and player-summed xG for/against, on both sides of the fixture, plus venue.
Its team-goal rates drive goal/assist shares and clean-sheet terms. The contextual
variant separately uses opponent-adjusted dynamic attack/defense. An extra manual
form bonus or a second strength multiplier would count this context again.

[Dixon and Coles (1997)](https://rss.onlinelibrary.wiley.com/doi/abs/10.1111/1467-9876.00065)
model football scores with Poisson regression and changing team performance.
[Macri-Demartino, Egidi and Torelli (2025)](https://arxiv.org/abs/2508.05891)
study dynamic attack/defense with adaptive borrowing between past and current form.
These support time-dependent context; their fitted methods or reported gains are not
claims about this implementation. We retain the repository's regularized Poisson
head rather than introduce or tune their models.

[StatsBomb's original team-analysis guide](https://blogarchive.statsbomb.com/articles/soccer/a-beginners-guide-to-analyzing-teams-using-stats/)
distinguishes goals and results from underlying xG creation/concession and explains
how finishing variation can separate them. Accordingly the candidate retains both
observed results and xG defense, with sample counts. A clean-sheet streak alone is
not interpreted as a calibrated next-match prediction.

## Causal metrics

`football_team_form.team_form_features` uses normalized player-fixture history. It
counts each paired club-fixture once, not once per player. Club goals and conceded
goals must agree within its player rows and with the opposing side. Player xG is
summed once per side; xGA is the opponent's sum. Duplicate player-fixture rows,
incomplete pairs, inconsistent scores, negative/nonfinite xG and naive timestamps
are refused. This does not reconstruct missing or ambiguous double-week xG.
This pairing check covers every season in the selected history and is stricter than
the v1 builder, which drops an unpaired side, so before the first real fit run the
form builder once over the selected archives and record whether every fixture pairs.

The target's season selects the current-season population. Older seasons do not
enter these form totals. Each club has season match/win/draw/loss counts, points per
match, mean goals and xG for/against, and clean-sheet rate. The last three and five
completed matches add sample counts, points per match, win and clean-sheet rates,
mean goals/xG for/against and goal/xG differences. Each target receives its own
club's and opponent's metrics. Venue remains the existing explicit fixture input.

For n completed matches, points per match is `(3 * wins + draws) / n`, and the
clean-sheet rate is the count of matches with zero conceded goals divided by n.
Rolling rates use the actual sample count when fewer than three/five matches exist.
A valid selected history with no eligible current-season matches gives zero metrics
and a zero match count, which distinguishes a cold start from a measured defensive
record. Missing or malformed selected sources are refused.

Every historical kickoff must be timezone-aware and more than three hours before
the decision cutoff. Training additionally excludes the entire target gameweek.
Target goals, points and other outcomes never enter the feature calculation. The
same form builder is used in every causal training fold and in live inference.
Forecasting later weeks freezes the information at the source cutoff; it does not
invent future form changes or infer an unplayed result.

## Optional learned effect and identity

`--team-form` selects `football_team_form_v1`. It requires an explicit repeated
`--training-season` selection and cannot combine with contextual or role-minutes
experiments. Only selected training sources are opened. Including current-season
history remains an explicit selection; without it these current-season metrics are
cold-start values. No new training population is chosen or run by this PR.
The first real fit may select only the archives 2022-23, 2023-24 and 2024-25 and
the captured season. The locked 2025-26 outcome population is refused by name at
the command and in the producer before any source is read, and any other archive
outside that list is refused before it is opened.
The first usable selected season supplies prior history only; at least one later
usable selected season must provide supervised rows for fitting.

The candidate fits the existing standardized Poisson team-goal head on the nine
accepted team columns plus own/opponent season sample size, points and clean-sheet
rates, and recent-five points, clean-sheet, goals and xG rates. The penalty remains
the existing alpha 0.1; no hyperparameter search is performed. Form influences the
learned goal intensity, then player goal/assist and clean-sheet expectations. It is
not a separate points bonus. Minute, participation, residual and defensive-action
heads keep their original feature inputs. Own/opponent form columns and venue are
reversed together when forecasting the opposing goal rate.
These eighteen form columns are fitted on one row per club fixture, and with one
archive plus the captured season only captured-season weeks from GW2 supervise them,
so the first real fit should select at least two supervised seasons and say so in
its record.

For standardized team inputs z, the fitted head uses
`lambda = exp(intercept + coefficients @ z)` with the existing Poisson objective
and L2 penalty. Player goal/assist shares use the own-club lambda. In minute bin b,
the clean-sheet term is `p_b * exp(-opponent_lambda * minutes_b / 90)` for bins
that reach 60 minutes. These terms enter the existing position-specific points
formula before captured availability is applied at the reader.

The new feature contract is `causal_football_fixture_team_form_features_v1`. Forecast
and optional fixture companion identify its windows, population, lag, head columns
and cold-start policy. Readers validate this identity rather than accept a relabeled
old document with missing or incompatible feature metadata. This validates the
declared feature contract; it does not independently prove the underlying fit.
Existing default feature tuples, model identity and publication stay
unchanged. The create-once publisher refuses a different document for the same
capture: use a separate experimental artifact root for comparison. Nothing switches
the accepted artifact automatically.

Captured availability continues to scale unconditional points and appearance once
at the existing reader. The new form head does not supply an injury forecast or
alter a 75/50/25/0 label. #1049 separately uses the effective appearance and points
for first-eleven/reserve selection. Native transfers, bank and chip resources still
belong to the existing planner. The existing three/five-week eligibility-information
adapter also accepts this externally scaled variant: its two declared next-deadline
branches average back to the original points and appearance without refitting form.
That experiment does not infer a player's recovery date or observe a future result.

## Validation and future models

Checks use fabricated fixtures and model fits only. Exact season/rolling summaries,
paired-source failures, player-row expansion, row reordering, cold starts, target
and same-week poisoning, the strict cutoff boundary, fit/inference consistency,
opponent reversal and published contract binding are tested. Existing default,
contextual, joint-role and immutable publication regressions also run. Synthetic
feature sensitivity proves a connected decision input, not better season results.

The owner also requested that these detailed metrics support later ANN experiments.
The versioned numeric table, stable own/opponent identities and explicit sample counts
are reusable inputs for a separately named model. An ANN is not fitted here. A future
proposal must declare its targets, architecture, training population and budget before
reading evaluation outcomes; split by decision date/gameweek rather than randomly
mixing player rows from the same fixture. Scalers, imputers and model parameters must
fit only the training fold, with feature cutoff/source identities retained.
Use a forward validation period for model selection and a separate later holdout;
freeze architecture and tuning before reading that holdout.

Compare that model against the accepted simple head on the same captures and work
budget. Assess point and participation predictions separately, then the resulting
frozen squad/transfer decisions under an accepted prospective protocol. Metric and
promotion gates remain owner decisions, including existing #1009/#1016 gates. No
neural architecture, evaluation threshold or promotion is inferred from this request.
