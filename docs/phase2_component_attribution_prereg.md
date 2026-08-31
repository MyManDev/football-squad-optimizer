# Phase 2 exact score-component attribution

Status: pre-registered exploratory development reuse. This study is not independent
confirmation, is not a promotion gate, and may not read the locked 2025-26 holdout.

## Question

The recorded squad distribution is centred but understates lower-tail risk. Prior diagnostics
did not localize the miss to the captain, a simple dependence correction, omitted player
location, raw residual pools, canonical decomposition or the proposed high-projection ordinary
return mechanism. This study asks a narrower question before any generative model is built:

> Which exact FPL score component carries the fixed selected XI's lower-tail miss?

No component model is fitted here. The optimizer decision, scenario matrix and projection stay
unchanged. Each counterfactual changes only the later realized score by replacing one realized
component surprise with its leakage-safe historical mean.

## Frozen population and chronology

The residual export, projection model, fold universe, optimizer settings, squad, starting XI,
captain, scenario configuration, seed, frozen shift, q10 definition and chronological history
are exactly those in `phase2_projection_conditional_returns`.

Roles remain:

- 2021-22 and 2022-23: screening;
- 2023-24: descriptive validation classification;
- 2024-25: already observed development sensitivity;
- 2025-26: locked and forbidden before any filesystem read.

Development folds use only `fold.prior_fold_ids`. Every 2024-25 fold uses one history frozen at
the end of 2023-24; no 2024-25 outcome enters its baseline. Target and future folds are rejected
at the attribution boundary. The recorded 2024-25 control PIT and S2 rate, prior fold count and
selected-starter population must reconcile before an artifact may be written.

## Exact fixture scoring identity

Raw fixture rows are read only for the explicitly declared seasons. Player-manager rows are
excluded and duplicate `(element, round, fixture)` records follow the canonical adapter's
keep-first policy. Stable player identity comes from the season roster. Fixture rows remain
separate until their score components have been calculated; this prevents two 45-minute
fixtures from becoming one 90-minute appearance.

For position `p` and fixture minutes `m`, the five fixed components are:

```text
appearance = 1(m > 0) + 1(m >= 60)
attacking  = goal_weight[p] * goals_scored + 3 * assists
defensive  = clean_sheet_weight[p] * clean_sheets
             + floor(saves / 3) + 5 * penalties_saved
             - 1(p in {GK, DEF}) * floor(goals_conceded / 2)
bonus      = bonus
negative   = -yellow_cards - 3 * red_cards
             - 2 * own_goals - 2 * penalties_missed
```

Goal weights are 6/6/5/4 for GK/DEF/MID/FWD. Clean-sheet weights are 4/4/1/0.
Every fixture and aggregated player-gameweek must satisfy

```text
total_points = appearance + attacking + defensive + bonus + negative
```

exactly. A mismatch, missing component, unresolved player identity or non-integral value refuses
the study. `starts`, xG/xA, archived fixture difficulty and season-final team strengths are not
read. The canonical data contract and production adapter are not changed.

## Historical component baseline

Fixture components are summed to player-gameweek only after the fixture identity check. For
each target starter and all five components, one common source pool is selected from the exact
allowed history:

1. same stable player and current position when at least 8 player-gameweeks exist;
2. same position;
3. pooled history.

The component baseline is the arithmetic mean of the selected pool. No expected-points band,
recent window, fixture-difficulty cell or result-dependent fallback is tried. Source counts and
player-source coverage are recorded. The target's realized minutes or score never selects its
source pool.

## Fold-level identity

Starter weight is 2 for the captain and 1 for every other starter. Bench players and automatic
substitutions remain outside the realized-score policy. Components are aggregated across a
player's fixtures before the captain weight is applied.

For fold `f`, component `k`, realized component `C`, historical mean `m`, target projection
`mu`, raw canonical scenario mean `Z_raw`, frozen shift `lambda`, and realized score `R`:

```text
D[f,k] = sum_i weight_i * (C[f,i,k] - m[f,i,k])
L[f]   = sum_i weight_i * (sum_k m[f,i,k] - mu[f,i])
H[f]   = sum_i weight_i * mu[f,i] - Z_raw[f]

R[f] - (Z_raw[f] + lambda)
  = sum_k D[f,k] + L[f] + H[f] - lambda
```

The weighted component total must also equal the canonical realized score. Both identities must
hold within `1e-9` on every fold before any attribution is interpreted. `L` and `H` are reported;
they are never hidden inside a component.

## Fixed component counterfactuals

The control reads the unchanged canonical scenario scores against `R[f]`. For each of the five
components, exactly one counterfactual is read:

```text
R_without_component_surprise[f,k] = R[f] - D[f,k]
```

This normalizes the realized component to its pre-fold historical expectation. The scenario
matrix, XI, captain and optimizer are not regenerated. Every arm uses the same scenario q10 and
the same strict `< q10` event; PIT uses the same `scenario_score <= realized_score` convention.

Realized weighted minutes, zero-minute starters, partial appearances and completed appearances
are reported beside the five components as descriptive mediators. They do not change the
classification because the current projection contract does not expose an expected-minutes
quantity suitable for this exact identity.

## Summaries and uncertainty

For every season and pooled, report control and component-normalized PIT, q10 event count/rate,
mean realized score and scenario mean. For each component report its fold surprise, source
coverage, the surprise contrast between control tail-failure and other folds, and the paired
reduction in q10 events after normalization.

Intervals use fold-clustered bootstrap with 5,000 resamples, 90% confidence and seed 0. Player
rows are never treated as independent. Screening and sensitivity seasons qualify the validation
reading but cannot replace it.

## Descriptive classification

A component is `localized` on 2023-24 only when all conditions hold:

1. at least 30 validation folds and exact score identities on every fold;
2. its mean surprise is more negative on control tail-failure folds than elsewhere, with the
   90% contrast interval's upper bound strictly below zero;
3. normalization reduces q10 failures, with the paired reduction interval's lower bound
   strictly above zero;
4. its normalized 2023-24 arm satisfies both recorded bands: mean PIT in `[0.43, 0.57]` and q10
   rate in `[0.04, 0.16]`;
5. 2024-25 does not reverse either direction: mean surprise contrast is at most zero and mean
   q10-event reduction is at least zero.

The study returns one of:

- `appearance_component_localized`;
- `attacking_component_localized`;
- `defensive_component_localized`;
- `bonus_component_localized`;
- `negative_component_localized`;
- `shared_component_failure` when more than one component passes;
- `component_not_localized` when none passes;
- `diagnostic_inconclusive` when identity, population or required support is unavailable.

Components are not ranked and the strongest point estimate is not selected. A localized result
only authorizes a separate preregistration for one simple component candidate. Shared,
not-localized or inconclusive results stop this branch; they do not authorize parameter sweeps,
alternate component groupings or production changes.

## Interpretation limits

Historical component means are a transparent attribution baseline, not a claim that they are
the best forecast. Fixture schedules in the completed archive do not prove what was known at a
past deadline, so fixture difficulty and target fixture count are not conditioning features.
Realized minutes are an outcome mediator, not a live input. This study changes no canonical
schema, feature, projection, scenario generator, optimization, live path or publication, and it
publishes no probability.
