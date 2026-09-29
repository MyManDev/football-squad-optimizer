# Observed rollout for three- and five-week decisions

The existing deterministic planner optimizes a fixed forecast path. Its observation
planner previously required every subproblem to be proved optimal and proposed
today's actions only from the baseline forecast. The five-week replay consequently
failed instead of returning a labelled feasible policy. This change adds an explicit
bounded mode and optional proposals from the supplied information scenarios.

## Decision model

At deadline t the state is the held squad, purchase/sale prices, bank, free transfers,
chip rights and the information available then. An action selects transfers, chip,
XI and captain subject to roster, budget and human constraints. State transitions
charge actual hits, accrue/cap free transfers, consume the relevant chip right and
restore the original squad and bank after Free Hit. Purchase values matter to future
sales; wallets alone are not a sufficient state representation.

The finite-horizon Bellman equation is

    V_t(s, I) = max_a { r_t(s, a, I) + E[V_(t+1)(T(s,a,O), I+O) | I] }.

Here the implemented approximation is two-stage: one common first action, followed
by one deterministic continuation for each mutually exclusive next-deadline
information node. Later decisions within a node do not branch again. It is not a
complete season MDP, and latent football outcomes are not observable information.

For a finite candidate menu A, the comparison is

    Q(a) = current_net(a) + sum_o p(o) * continuation_net(a,o).
    chosen = argmax_(a in A) Q(a).

Observation-specific optimizers may propose first actions. They never choose a
different first action for each node: every proposal is rescored in every node.
The baseline action menu and feasible hold action remain in A. The returned
baseline_candidate_indices allow an ablation using the EXACT same continuations.
Consequently the chosen feasible-policy value cannot be below that baseline-menu
value in this comparison. This is a finite-menu, supplied-model statement, not a
guarantee of realized points, optimal season return or improvement at every later
replanning step. Such a policy improvement theorem needs consistent continuation
evaluation; bounded solvers and changing beliefs do not automatically provide it.

The distinction follows the rollout and fortified-rollout discussion in
[Bertsekas, MIT lecture 9](https://ocw.mit.edu/courses/6-231-dynamic-programming-and-stochastic-control-fall-2015/resources/mit6_231f15_lec9/).

## Proof, preferences and resource value

Strict mode remains the default. Bounded mode accepts OPTIMAL or FEASIBLE plans,
enables the existing hold guard and exposes FEASIBLE_RESTRICTED_MENU when any
required primary solve is unproved. UNKNOWN or an incomplete positive-probability
branch is an error, never a dropped scenario. Even OPTIMAL_RESTRICTED_MENU is only
conditional on the generated menu and integer-scaled subproblem objective; reported
scores are unrounded. No global MDP bound is implied.

Keep/avoid, no-hit and save-chip preferences constrain proposal generation, hold,
every continuation and the paired extra-FT solve. Extra-FT value is reported only
when both continuation optima are proved (or zero when already at the FT cap).
The difference of two merely feasible lower bounds is not an option-value estimate.
No guessed terminal FT/chip bonus is fitted. Beyond-window resource value and
multi-stage injury information remain open limitations.

Top100 weight remains a user preference. Comparisons may show 0, 20 and 50 as three
examples within the existing menu, never as learned best weights. The objective uses
the existing lagged count multiplier; actual forecast points are rescored on the
unweighted node tables. A rise in preference utility is not a prediction improvement.

## Bayesian optimization and evidence

BoTorch already exists as an optional research implementation in this repository.
BO searches a defined expensive objective; it cannot supply missing information
transition probabilities or certify a policy. Previous chip-constant searches were
not distinguishable from zero weekly improvement; the coarse GP terminal-value
study lost to its baseline. We therefore introduce no new fitted constants here.
If later tuning becomes justified, split chronological training, policy selection
and future evaluation, compare BO with equal-budget random/grid search, and score
realized net returns and downside rather than its own predicted objective. See the
[official BoTorch closed-loop tutorial](https://botorch.org/docs/next/tutorials/closed_loop_botorch_only)
for objective evaluation and acquisition; noisy evaluation is not a licence to treat
correlated weeks as independent replications.

The paired experiment uses immutable captured forecasts, constructed squads and
declared information stresses, not owner holdings or future outcomes. It can test
causality, legality, failure rate, menu value and sensitivity. It cannot establish
forecast accuracy, calibrated injury probabilities or a live promotion. Report all
failures and both unweighted points and preference utility. Existing prospective
protocols and frozen candidate identities remain untouched.

## Explicit lookahead and application review

`planning.lookahead.optimize_with_lookahead` solves an explicitly supplied longer
forecast and retains the full feasible path. It separates the selected 3/5-week
net points from the tail points, and refuses absent tail weeks or stacked terminal
constants. This models later opportunities directly rather than guessing a scalar
end value. It may sacrifice short-window points to preserve a useful resource.
Its own extended horizon still has an edge; it is not a season-level solution.
The current live forecast artifact covers five weeks only: that supports a tail for
a three-week request, but NOT a five-week request. The latter needs a separately
provided longer decision-time forecast. No later calendar is fabricated or copied.

`application.planner_review.review_observed_plans` is the opt-in offline entry point
for the supplied information scenarios and a chosen Top100 setting. It checks an
explicit source, probability basis and timezone-aware evidence/issue/decision dates.
It requires lagged counts loaded through the existing full Top100 evidence gate.
The selected setting remains selected, even when another option has a larger
weighted objective. Each option carries raw expected net, minimum information-node
net (NOT a quantile), expected hit cost and the full rollout proof record. Declared
provenance does not prove probability calibration. No website default or publication
is changed by calling this service.

Transaction prices remain the core planner's supplied per-week prices. The first
purchase is rebased using the new purchase price; Free Hit preserves the original
book. Later buy/sell/rebuy cycles within a deterministic continuation are NOT a full
purchase-lot model. Tests cover first-purchase rises, losses and Free Hit restoration;
we do not claim future price forecasting or universal path-dependent sale accuracy.
