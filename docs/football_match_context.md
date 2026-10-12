# Experimental PL match context

Issue #1053 adds the explicitly selected `football_match_context_v1` candidate.
Its feature identity is `causal_pl_workload_venue_features_v1`. This implementation
prepares a forecast experiment using synthetic checks. It reports no real-season
forecast gain, no prospective result and no promotion of the candidate.

The existing fixture candidate already has own and opponent goals/xG, venue,
recent three/five appearance and minute summaries, and days since a player's
last appearance. Calendar-day workload adds a different description: completed
player exposure and distinct club fixtures inside elapsed-time windows. The
venue additions describe each club's attack and defense at the relevant venue,
with the observations and missingness required to interpret those estimates.

## Implemented feature and head contract

`match_context_metadata()` is the normative exact feature/head contract. Both
the served document and its fixture companion carry this metadata and the
feature identity. Readers refuse missing, altered or mismatched metadata before
accepting the new forecast. The reader's horizon and first-week projection keep
the new identity. Existing model versions and their default feature identities
remain accepted independently.

The minute head learns the existing features plus the declared context features.
The club goal head learns existing own/opponent strength plus declared club
context features. The per-appearance residual and defensive-action count heads
retain their existing features. Opponent goal prediction reverses the own/opp
features and venue coherently. Goal rates feed player goal/assist allocation and
clean-sheet expectation through the existing scoring algebra. No manually chosen
fatigue deduction or second opponent multiplier is added.

Workload is explicitly **PL-only**. It is computed from normalized completed PL
history, not cup, European or international fixtures. A missing external match is
not evidence of rest. Player histories and distinct club fixtures are counted
separately so the eleven players in a match do not count as eleven club matches.
Future target rows provide identity, fixture and venue context, never
target goals, minutes or other results. Future played minutes are not fabricated.

Training and inference call the same causal context feature builder. Training
excludes the entire target gameweek and outcomes unavailable at the fold cutoff.
Historical training uses the target week's first kickoff as a causal pre-match
proxy, not as proof of a captured historical FPL deadline information state.
Inference freezes completed history at the capture cutoff. Selected training
seasons are explicit; the first usable selected season supplies priors only.
The locked 2025-26 outcome population is refused by this new option. Existing
accepted defaults keep their independent source-selection behavior.

The model produces conditional fixture components. Captured eligibility is
carried unapplied in the companion and enters weekly expected points and
appearance once through the existing reader rule. Values of 0, 25, 50 and 75
retain their captured meaning; this work does not fit an injury model or classify
all low flags as absent. The next-deadline information adapter can invert only
that known external eligibility factor, preserving the learned minute law and
the mean of its two branches. Contextual pre-allocation availability and role
transition options are incompatible with this separate candidate.

## Mathematical handoff

Let \(z_m(x)\) be the minute-head feature vector, standardized using training
rows only. Its multinomial logistic head gives

\[
\pi_b(x)=\frac{\exp(\beta_{0b}+\beta_b^\mathsf{T}z_m(x))}
{\sum_{c\in C}\exp(\beta_{0c}+\beta_c^\mathsf{T}z_m(x))}.
\]

\(C\) contains the fitted minute categories; an unobserved category has zero
predicted mass. Category zero means no minutes. The remaining categories are
positive minutes below 60, at least 60 below 90, and at least 90. Their recorded
training means are \(m_b\), with the existing fixed means used for missing bins.
The conditional fixture outputs are

\[
E[M]=\sum_b\pi_b m_b,\qquad
q_f=1-\pi_0,\qquad p_{60}=\pi_2+\pi_3.
\]

For standardized club features \(z_t(x)\), the existing regularized Poisson head
uses a log link:

\[
\lambda_{\rm own}=\exp(\theta_0+\theta^\mathsf{T}z_t(x)),\qquad
\lambda_{\rm opp}=\exp(\theta_0+\theta^\mathsf{T}z_t(\operatorname{swap}(x))).
\]

The swap exchanges every own/opp context pair and reverses home venue. The
clean-sheet contribution of the positive long-minute bins is

\[
p_{\rm CS}=\sum_{b\in\{2,3\}}\pi_b
\exp(-\lambda_{\rm opp}m_b/90).
\]

These are declared working model identities, not a calibrated fatigue rule.
Player goals and assists use the existing per-90/minute-weighted club shares;
residual and defensive-action heads retain their previous feature design.

Let \(a\) be the existing captured eligibility multiplier. For one fixture, the
reader applies \(q=a(1-\pi_0)\). For multiple fixtures in one gameweek, it applies

\[
q_{\rm GW}=a\left[1-\prod_f(1-q_f)\right],\qquad
E[P_{\rm GW}]=a\sum_f E[P_f].
\]

Thus eligibility is shared once across the gameweek. Conditional fixture
appearance independence is the retained approximation; multiplying each
fixture by \(a\) before the product would implement a different model. The
component-basis reader reconstructs the same weekly quantities, and the
next-deadline eligible branch removes only \(a\), preserving the fitted
conditional minute law.

## Research and permitted-source expansion

The following extensions are candidates for later separately declared work.
They require their source permission, capture and evaluation gates before actual
ingestion or fitting. Their ranking reflects practical implementability, not a
measured forecast improvement.

| Order | Extension                          | Intended head                                                                          | Additional input and validation                                                                                                                                                                                              |
| ----- | ---------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | Complete rest and congestion       | Start/cameo/minutes first; club goals only as a separate ablation                      | Completed player minutes and club schedules across cups, Europe and internationals, with explicit competition coverage. Keep future scheduled congestion separate from observed workload.                                    |
| 2     | Projected XI strength and absences | Own/opponent goals and player scoring shares                                           | Historical on-field intervals, predeadline projected roles, persistent player identity and training-fold contribution ratings. Missing creator/defender exposure is separate from the focal player's own eligibility factor. |
| 3     | Role and set-piece shifts          | Open-play, penalty, direct-free-kick and corner goal/assist channels                   | Captured taker ranks plus historical event takers and exposure. Rank is not an event probability. Partition channels without counting penalties or assists twice.                                                            |
| 4     | Tactical defensive matchup         | Goal/concession rates, player attacking shares and position-specific defensive actions | Event phases, shot zones/types, crosses, headers, set-piece concessions and possession exposure. Preserve provider definitions and map actual FPL defensive-action categories.                                               |
| 5     | New-player quality prior           | Regularized scoring/creation prior before enough PL observations                       | A licensed timestamped quality source, with age, position, league and missingness. Compare with the same model without this prior. No direct market-value-to-FPL-points multiplier or automatic starting-role bonus.         |

Fixture congestion has mixed reported performance effects. The systematic review
does not justify a fixed fatigue-to-points rule or a new injury calibration.
Use continuous workload inputs and compare the learned minute effect separately.
[Julian, Page and Harper, 2020](https://eprints.glos.ac.uk/8915/).

football-data's documented match resource exposes competition, scheduled UTC date,
status, lineups and substitutions. Actual access must cover the required
competitions and fields; a PL feed alone cannot establish total workload.
Capture schedule revisions as they were known at the forecast cutoff.
[Provider match contract](https://docs.football-data.org/general/v4/match.html).

Regularized plus-minus and possession-based adjusted contribution models offer
methods for projected unit strength that control for teammates and opponents.
Simple on/off averages confound those contexts. Fit contribution ratings only
inside each training fold, then aggregate the captured projected unit exposure.
[xG plus-minus](https://arxiv.org/abs/1706.04943),
[possession adjusted plus-minus](https://arxiv.org/abs/2407.17832).

Confirmed PL lineups are ordinarily available 75 minutes before kickoff, while
the FPL deadline precedes the first kickoff by 90 minutes. Therefore the first
match's confirmed XI ordinarily arrives after that decision. This inference
requires a captured predeadline projected XI, rather than retrospective use of
the confirmed lineup.
[Official lineup timing](https://www.premierleague.com/en/news/4081650),
[FPL rules](https://www.premierleague.com/en/news/4661029).

The project already captures FPL penalty, direct-free-kick and corner/indirect
rank fields. Historical channel rates and role redistribution need additional
event/exposure evidence. Current taker lists must not be backfilled into earlier
forecasts. [Official set-piece explanation](https://www.premierleague.com/en/news/2231236).

Opta and Hudl document event/tracking inputs for shot quality, phase, territorial
and positional analysis. Their commercial coverage and permissions must be
confirmed before a new source is selected. Selected open datasets are useful
for methodology but do not establish current PL coverage.
[Opta event definitions](https://www.statsperform.com/opta-event-definitions/),
[Opta Vision](https://www.statsperform.com/products/opta-vision/),
[Hudl phases of play](https://www.hudl.com/blog/phases-of-play-hudl-statsbomb),
[Hudl open-data scope](https://github.com/hudl/open-data/blob/master/README.md).

Transfermarkt describes a community valuation influenced by age, potential,
performance, reputation, demand and league financial context. That valuation is
not an FPL price or a direct performance measurement. A quality prior would need
age/position/league adjustments fitted within training folds and an as-of
valuation capture; later valuations must never be substituted into earlier
predictions. [Transfermarkt methodology](https://www.transfermarkt.com/navigation/mwdefinition).

Transfermarkt's terms section 11.1 restricts automated copying and use of its
content for model training or development. A manual export alone does not
override those stated restrictions. Before any actual Transfermarkt-derived
model input, ask the owner for a permitted source and authorization covering
model development/use. This implementation neither collects nor ingests values.
[Transfermarkt terms](https://www.transfermarkt.com/intern/anb).

## Capture and prospective gates

Every additional source must record its permitted use, provider/schema version,
publication precision, publication time, capture time, immutable source identity,
persistent player/club mappings and competition coverage. Missing data is
distinct from a measured zero. Only information available before the decision
cutoff may enter a fold; final revised fixtures, roles and values are not
retrospective evidence that those facts were known earlier.

Declare the permitted population, targets, preprocessing, architecture, training
budget, metrics and acceptance gates before fitting a new experiment. Use causal
date/gameweek folds, train-only scaling/imputation and regularization, forward
validation and an untouched later evaluation with tuning frozen. Feature/head
ablations and a combined model must share the declared evaluation population and
budget. An ANN is a future preregistered architecture choice, not part of this PR.
Existing #1004, #1009 and #1016 decisions and protocols remain binding.

The later combined configuration needs actual #1049 and #1052 merges and its own
review. The fixed-fifteen route must preserve legal squad/XI constraints,
captain/vice behavior, compatible ordered outfield reserves, goalkeeper-only
cover, chip resources, transfer costs and the complete action lock. A minute-long
cameo blocks an autosub; FPL's card-only participation rule and captain's separate
no-minutes fallback also need preserved resolver checks. None of these rules
requires guessed correlations between injuries.

Shared prediction/planning/source changes require Ibo review. Actual merge waits
until after the GW6 freeze and outside a weekly run. This work does not enqueue,
merge, run the weekly operation or promote a forecast identity.
