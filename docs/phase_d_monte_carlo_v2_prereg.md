# Phase D — component-aware Monte Carlo V2, pre-registration

Status: **frozen before any production code.** This document is committed ahead of the
implementation it describes, so the structure below cannot be chosen after seeing an output.

Scope of this pre-registration: the *foundation* only — the input contract, the paired
conditional residual pool, and a deterministic sampler. It registers **no numeric threshold**,
promotes nothing, changes no live behaviour, and produces no probability for a user.

## 1. What V1 already models, and stays untouched

Scenario V1 (`squadopt.scenarios`) already decomposes point residuals into common-gameweek,
team-gameweek and idiosyncratic shocks, draws them empirically from out-of-sample history under
a deterministic seed, and feeds a scenario-aware CVaR optimizer. None of that is redesigned,
copied, or re-derived here. `generate_scenarios()` and every V1 result stay **bit for bit**
unchanged, and that claim is verified by fingerprint rather than by "the tests still pass".

## 2. What V1 does not model, and Phase C now measures

V1 works on a single point residual per player. It has no representation of:

- the **appearance mixture** — whether a player featured at all;
- **conditional minutes** given an appearance;
- **conditional points** given an appearance;
- the **non-appearance atom at exactly zero**, which is not a small residual but a different
  outcome;
- the **dependence between minutes and points**, which is the reason a squad of nine
  sixty-minute players is not the same risk as a squad of nine ninety-minute players.

Phase C's out-of-fold table (`phase_c_component_oof_v1`) carries the targets and conditional
expectations these need. This foundation is the seam that lets a later, measured step use them.

## 3. The frozen structure

For one player `i` and one decision week:

```text
A_i ~ Bernoulli(p_i)

A_i = 0:
    M_i = 0
    Y_i = 0

A_i = 1:
    M_i = clip(mu_minutes_i + epsilon_minutes_i, 0, 90 * fixture_count_i)
    Y_i = mu_points_i + epsilon_points_i
```

with `p_i = appearance_probability`, `mu_minutes_i = expected_minutes_if_appearance`, and
`mu_points_i = raw_expected_points_if_appearance`.

**`Y_i` is not clipped at zero.** An FPL score can be negative — a card, an own goal, a
conceded-goals penalty — so clipping the scenario outcome would delete real downside and quietly
narrow every risk statistic computed from it. The non-negativity that the optimizer's *expected
points* input obeys is a separate public contract about an expectation, and conflating the two
would import a constraint on a mean into the support of a distribution.

**Non-appearance is an exact zero, not a small draw.** Both minutes and points are exactly zero,
because a player who did not feature scored nothing rather than approximately nothing.

## 4. Residual source and the leakage rule

`epsilon_minutes_i` and `epsilon_points_i` come only from out-of-fold residual history that is
**strictly earlier** than the decision fold being generated. For a component-model row that was
observed to appear:

```text
minutes_residual = minutes_target - expected_minutes_if_appearance
points_residual  = points_target  - raw_expected_points_if_appearance
```

Rules frozen here:

- only rows with `appearance_target == 1` enter the pool — a conditional residual conditioned on
  an appearance that did not happen is not defined;
- a row whose conditional target is missing is **excluded**, never filled with zero;
- the target fold may not appear in its own history, and every history fold must precede the
  target;
- `direct_control` rows produce no conditional residual, because they carry no component
  prediction to take a residual against;
- **the minutes and points residuals are drawn together, from the same historical row.** That
  pairing is the first candidate mechanism for preserving minutes–points dependence, and taking
  the two marginally would destroy exactly the structure this phase exists to capture;
- insufficient history is an explicit refusal. There is no silent fallback, and no arbitrary
  position or team fallback hierarchy is introduced here.

## 5. What this foundation deliberately does not do

- **It does not combine the paired draw with V1's point decomposition.** The paired draw already
  carries the whole point residual; adding V1's common/team/idiosyncratic shocks on top would add
  the residual twice. Combining them correctly is a measured step, not a foundation step, so this
  PR is limited to the appearance-plus-paired-residual core rather than inventing a correlation
  structure that looks right and double counts.
- **No second team-correlation system is written.** When correlation is integrated it reuses the
  existing decomposition.
- **No start probability is invented.** The start component is unavailable; a fabricated one would
  be indistinguishable from a measured one downstream.
- **No autosub, vice-captain, bench order or captain multiplier.** Those belong to the official V2
  decision scorer, not to a player-level generator.
- **No value is invented for `direct_control` rows.** A decision-level run needs a frozen control
  fallback bound by exact key from another artifact; until that exists, the rows stay unusable
  rather than filled.
- **`not_requested`, `available` and `missing` remain three distinct states.** Collapsing them
  would turn "we did not ask" into "there is nothing", which are different claims.

## 6. Structural correctness conditions

These are the conditions frozen for this foundation. They are structural, not numeric: no
promotion threshold, dispersion coefficient or gate is registered here, and none may be chosen
after seeing an output.

1. Same seed and same input produce the same scenario matrix and the same fingerprint.
2. A non-appearance draw yields exactly zero minutes and exactly zero points.
3. An appearance draw yields minutes inside `[0, 90 * fixture_count]`.
4. A blank gameweek (`fixture_count == 0`) yields zero.
5. The target fold is absent from its own residual history.
6. Every history fold precedes the target fold.
7. The locked 2025-26 holdout is refused.
8. Inputs are not mutated.
9. Player order is preserved exactly between the input and the scenario columns.
10. A negative realizable point outcome survives to the scenario matrix.
11. Paired residuals keep minutes and points from the same historical row.
12. V1's API and results are unchanged.

## 7. Provenance

Every scenario input carries, separately from its per-player rows: the Phase C table SHA, the
roster SHA, the model version, the feature/target/dataset contract versions, the target season
and gameweek, and the deterministic seed. A scenario set that cannot name where its inputs came
from is not evidence.

## 8. Status

No binding measurement is run in this pre-registration or in the foundation PR it describes. The
locked 2025-26 holdout is not read, listed or hashed. No model is fitted or tuned, and the live
recommendation path is unchanged.
