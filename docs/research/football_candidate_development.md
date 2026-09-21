# Fixture football candidate and observed planning

This is an opt-in application path for evaluating the team-share football candidate.
It leaves the promoted live predictor unchanged. A development improvement is not
independent evidence and does not authorize an automatic model promotion.

The [21 September results](football_candidate_results.md) and
[portable measurement record](football_candidate_development_record.json) retain the equal-solver
comparison and negative ablations. The role transition worsened future errors and remains off
by default; the full-match CS approximation does not replace the analytic point mean.

## Five changes

1. Compare the frozen candidate and control with the same solved objective and completed
   tie-break. A FEASIBLE control against an OPTIMAL candidate confounds model and search
   quality. Preserve all attempts, unresolved weeks and input hashes.
   `optimize_squad(..., linearization_level=2)` makes the LP2 proof setting available
   for both primary and tie-break phases; omission preserves the existing default.
2. `FixtureFootballModel` decomposes points into minute-bin appearance/60-minute credit,
   team goals allocated by player xG share, assists allocated by xA share, clean sheets,
   negative-binomial defensive contribution and a conditional residual. Version
   `football_team_share_v1` reproduces the measured research head. The separately named
   `football_team_share_role_transition_v2` advances the four-bin minute distribution
   through position-level empirical transitions for unseen future fixtures. Transitions
   use a fixed pooled Dirichlet prior of ten transitions; there is no parameter search.
   `build_football_horizon` forecasts every fixture from the same information state and
   sums double weeks. A current blank is zero only for that week.
3. `optimize_observed_recourse` evaluates a bounded menu of first-week CP-SAT decisions,
   including hold when legal. A first-week decision is fixed before observation. Each
   mutually exclusive next-deadline information node gets one continuation, irrespective
   of how many hidden future outcomes could produce that information. This is a two-stage
   rollout over a restricted menu, **not** proof of a globally optimal stochastic policy.
4. `sample_football_events` draws shared home/away match goals and allocates credited
   goals and distinct assisters. Clean sheets share the opponent's zero-goal event.
   All candidate squads face identical worlds. Player minute draws remain independent;
   this is not an eleven-player lineup or measured substitution-hazard model. The CS
   event uses a full-match conservative approximation, differing from v1's minute-bin
   exposure expectation. Residual bonus/card effects are conditional means, not calibrated
   event distributions. Consequently neither the mean nor tail of these draws should be
   assumed identical to v1's analytic forecast. Own-goal assists and other FPL attribution
   exceptions are not separate simulated events; the simulator's assists-per-credited-goal
   bound is its approximation, not the full FPL rule.
5. Each continuation can be solved again with one more available free transfer. The paired
   net-point difference is a state-dependent option-value diagnostic inside the explicit
   horizon, not an extrapolated terminal coefficient. At the cap the extra value is zero.
   Optional rival scoring reports common-world one-week `P(win) + 0.5 P(tie)` separately
   from expected multiweek points. The first half of the draws selects a menu member;
   the second half evaluates that fixed selection, reducing simulation-selection optimism.
   This held-out simulation is not independent real-world evidence. A supplied rival is
   not an authenticated Top100 cohort.

Recourse comparison requires zero bench and terminal weights, discount one and the actual
hit charge in both the objective and reported scores. Its conditional value otherwise
would be comparing different objectives. Buy/sell accounting carries the owner's purchase
book and rebases purchases made at the first deadline before the continuation. Chips are
not modeled on this new path; existing chip-aware production paths remain separate.

The scoring adapter also preserves explicit card participation. A player receiving a card
without minutes participates for autosub purposes; real minutes are unchanged and captain
fallback still depends on minutes. Legacy documents lacking all card metadata retain their
old shape. Partially supplied card metadata is rejected. The older `settled_outcome_v1`
export does not carry card participation and cannot by itself reconstruct this edge case;
use the captured live payload for official squad replay.
These participation/captain distinctions follow the
[official FPL rules](https://www.premierleague.com/en/news/4661029).

## Application and offline entry point

The point expectation is `P(M>0) + P(M>=60) + goal_value*E(goals) + 3*E(assists)
+ cs_value*P(CS credit) + 2*P(DEFCON threshold) + E(residual)` under the relevant season's
scoring rules. Goal shares sum to one within each club/fixture. The defensive count has
mean `mu = rate90*M/90` and variance `mu + mu²/kappa`; tail probabilities are mixed over
the minute bins. The original nonnegative total floor is retained for v1 parity.

For the k-th unseen fixture, role probabilities are `pi_1 * T^(k-1)`. No role transition
is consumed by a blank week. This stationary transition approximation is an ablation;
uncertainty about injury and tactical roles is not replaced by knowledge of future minutes.

For a first action `a`, the rollout value is immediate net points plus
`sum_i q_i * optimal_continuation_net_points(state_after_a, information_i)`. Only the
continuation sees `information_i`. `Delta_FT(s) = V(s, FT+1) - V(s, FT)` compares the same
state, forecasts, horizon and actual hit charge, capped at the free-transfer limit. The
comparison maximizes the scaled CP-SAT point objective; sub-scaling-unit differences
are numerical resolution, not a claim of greater forecast accuracy.
That objective uses projected starting-player/captain points. Autosub-aware scenario scores
are reported afterwards; the deterministic planner does not optimize their nonlinear mean.
The v1 expectation also lacks a separate zero-minute-card head, even though actual squad
scoring now preserves that participation case.

`squadopt.application.football_candidate.preview_football_candidate` connects fitted
model, captured roster/calendar, purchase book, planner, optional observation nodes,
official bench/vice completion, common football scenarios and optional rival evaluation.
It returns versioned projections and diagnostics without publishing an owner decision.

An explicit input bundle can be exercised without network or live-state access:

```sh
python scripts/preview_football_candidate.py --bundle artifacts/candidate/bundle.json \
  --output artifacts/candidate/preview-01 --samples 256 --seed 0
```

The output directory must be new. The JSON bundle names these fields:

```json
{
  "contract_version": "football_candidate_bundle_v1",
  "training": "training.csv",
  "history": "history.csv",
  "roster": "roster.csv",
  "calendar": "calendar.csv",
  "decision_cutoff": "2026-09-25T17:00:00Z",
  "captured_at": "2026-09-25T16:30:00Z",
  "source_snapshot_id": "replace-with-real-capture-identity",
  "season": "2026-27",
  "gameweeks": [6, 7, 8],
  "bank_tenths": 10,
  "free_transfers": 2,
  "holdings": [{"player_id": 123, "purchase_price_tenths": 50}],
  "role_transitions": false,
  "candidate_count": 3,
  "observations": []
}
```

The holdings example is abbreviated: a real bundle needs all 15 legal squad members.
Optional observations have `id`, positive `probability` summing to one, and `table`, a
CSV containing a validated `PlanningHorizon` over exactly the future weeks/player universe.
Probabilities and posterior forecasts must be determined before seeing held-out results.
The script hashes all named inputs and emits projections, components, scenario scores and
a report. It never labels caller-supplied timestamps as independently verified evidence.

Roster columns are `player_id,name,team_id,position,price_tenths,club`, using stable IDs.
Calendar columns are `fixture,club,opponent,home,GW,kickoff`, with both opposing sides.
History is normalized player-fixture data including season, kickoff, position, minute
bins/appearance/60-minute flags, starts, goals/assists/xG/xA, CS, defensive contribution
and own/opponent score. Training additionally contains the causal columns defined by
`prediction.football_features.FEATURES`, `feature_cutoff`, and `residual_target`.
Every training feature cutoff must precede its match. Training features must exclude
the entire target gameweek and unsettled matches; checking a timestamp alone cannot prove
the feature builder actually did this. History must be settled before the model cutoff.

## Evidence and acceptance

Do not tune on the locked comparison. Keep per-season, per-origin and per-lead results,
missing-outcome coverage, source hashes, calibration losses and solver status. A candidate
must first reproduce its research implementation, then beat its fixed comparator. New
role or full-match-CS heads are separate ablations, not silent corrections to the winner.

Historical final fixture calendars and reused development seasons cannot demonstrate
prospective, deadline-valid availability or unseen generalization. That requires captured
inputs, an unchanged model/protocol, and subsequent settled labels. Do not invent future
injury observations or authenticated rival histories to fill that gap. Negative ablations
stay inactive. Full quality gates and synthetic application E2E establish implementation
correctness; they do not establish a live predictive gain.
