# Frozen football planning replay

Measured on 28 September 2026. The
[earlier forward study](football_component_ablation.md) found a five-week solver
incumbent worse than holding. This replay isolates the existing feasible-hold guard
and repeats bounded observation-contingent planning on the same control forecasts.

## Fixed comparison

The 667-player control projection table, constructed initial squad, bank, one free
transfer and no chip rights are unchanged. Both 3/5-week horizon fingerprints match
the previous study exactly. CSV floats are read with round-trip precision. Buy and
sell prices stay equal to the saved prices; no price or injury model is introduced.

Each primary solve retains 120 wall seconds / 60 deterministic units, one search
worker and seed zero. The protected method additionally runs the existing hold
probe, bounded at 30 wall seconds / one deterministic unit. Recourse invokes multiple
solves, including the extra-free-transfer diagnostic. Total method budgets are not
equal, so this is a quality/safety replay, not an equal-cost algorithm contest.

The two equally weighted future information nodes apply the same +/-30% update
to the previously nominated player. These are sensitivity cases, not calibrated
injury probabilities or realized scores. Recourse uses one proposed first action
plus the explicit hold alternative and requires proved feasible subproblems.

## All eight cases

| Weeks | Method | Expected net points | Hits | Status | Wall seconds |
|---|---|---:|---:|---|---:|
| 3 | hold | 162.933 | 0.0 | OPTIMAL | 0.044 |
| 3 | unprotected | 165.837 | 0.0 | OPTIMAL | 39.717 |
| 3 | protected | 165.837 | 0.0 | OPTIMAL | 21.003 |
| 3 | recourse | 167.860 | See branches | OPTIMAL_RESTRICTED_MENU | 67.122 |
| 5 | hold | 273.903 | 0.0 | OPTIMAL | 0.064 |
| 5 | unprotected | 248.401 | 28.0 | FEASIBLE | 41.377 |
| 5 | protected | 274.334 | 0.0 | FEASIBLE | 36.804 |
| 5 | recourse | Unverified | Unverified | FAILED | 41.472 |

At three weeks the protected and unprotected plans agree at 165.837, versus
162.933 for holding. The restricted recourse value reproduces 167.860. That extra
2.023 is conditional on the authored information scenarios, not measured season profit.

At five weeks the unprotected incumbent reproduces 248.401 with 28 hit points, below
the 273.903 hold score. Protection returns 274.334 with no hits. It improves the
incumbent by 25.933 and exceeds holding by 0.430 projected points. The objective-scale
proof gap falls from 33.593 to 6.662, but both are FEASIBLE, not proved optimal.
Objective bounds use scaled/rounded solver units and need not equal raw displayed points.

Five-week recourse still fails its proof requirement. The failure is preserved:
`Recourse comparison requires proved feasible plans.` It is not replaced by a
successful-looking fallback and no budget is expanded after seeing the result.

Wall times are single runs on a shared development machine. The lower protected
times do not establish general speed or production capacity. No live load was tested.

## Operational interpretation

The production transfer-horizon adapter already enables `protect_hold=True` for
both ordinary planning and chip strategy. This replay validates that existing
mechanism on the previously troublesome forecast, rather than adding a duplicate.
The benchmark uses its declared research objective and transfer policy; it is not
a replay of every member request or the deployed service configuration.

Keep the guard and the visible solver limitations. The measured bottleneck is
proving five-week combinatorial decisions, not evidence that another service,
database, cache or unrestricted search budget is needed. Expanding the action menu
or fitting a terminal value needs a separately declared quality/cost experiment.

This does not solve the known chip-tail limitation: a stationary tail estimated
only from the selected window cannot exceed that window's best opportunity.
Triple Captain and Bench Boost expected-failure tests remain explicit. A season-wide
chip policy still needs capture-time opportunity evidence and prospective validation.

## Reproduction

`python scripts/replay_football_planning.py --study <saved-forward-study>`
`--output <fresh-directory>`

The [record](football_planning_replay.json) contains all cases, branch diagnostics,
proof gaps, input/source hashes and environment versions. The runner never trains
a model, reads live operational state, changes production settings or promotes a policy.
