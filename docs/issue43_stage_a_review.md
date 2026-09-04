# Issue #43 Candidate — Stage A Review by the Optimization/Evaluation Side

Step 4 of [candidate_declaration_review.md](candidate_declaration_review.md) assigns
this side one job: confirm that the changed component is singular and that every
frozen component in the declaration is actually unchanged in the code. This is that
review, against [issue43_candidate_declaration.md](issue43_candidate_declaration.md)
(declaration `f72962a1…`, benchmark configuration `b64a3ab9…`) at commit `93a87d6`.

It is a review of code, not of results. No formal run was made, and nothing here is
gate evidence.

## How the review was done

The candidate reaches the frozen pipeline through one seam: `production_projection`
gained a `rate=` argument (`src/squadopt/prediction/production.py`), and the candidate
builder (`src/squadopt/backtest/learned_candidate.py`) injects a rate through it. So
the review has two halves. First, the seam: does the injected rate replace exactly the
value the frozen stage produced, and nothing else? Second, the builder: is every frozen
component reached through the existing code rather than reimplemented? Diff read:
`git diff 1e5196e..93a87d6 -- src/squadopt/prediction src/squadopt/backtest/learned_candidate.py`.

## The changed component is singular

`expected_points_rate`. In `production_projection` the only branch that differs from
the frozen path is the assignment of `rate_values, rate_source`; the minutes stage runs
first and unchanged, the price prior, the "absent" and "measured" masks, the two-stage
product, and the source bookkeeping are the same statements as before with `rate`
renamed to `rate_values`. An injected rate that does not share the feature index is
refused rather than reindexed (`_validated_rate`), which is the right refusal: a
reindex would pair one player's minutes with another's scoring, and no downstream check
could see it.

## Frozen components, one by one

| Frozen component | Where it lives | Finding |
| --- | --- | --- |
| `expected_minutes_stage` | `production.py: expected_minutes` | Untouched by the diff; called first in `production_projection` exactly as before, on the same `settings.minutes`. (The test named `test_the_expected_minutes_stage_is_unchanged` only checks that both paths project the same players; the evidence here is the diff, not that test.) |
| `cold_start_ladder` | `production.py: expected_points_per_90` (frozen) vs `learned_rate.py: learned_points_per_90` (candidate) | Same rungs in the same order: carry-over first (shrunk), in-season on top, missing below. **One observation, not a defect** — see below. |
| `availability_post_processing` | `prediction/integration.py`, live rule | Not in the diff. Applied after projection on both paths. |
| `two_stage_combination` | `production.py: production_projection` | Same product `expected_minutes / 90 × rate`, same masks; the injected rate enters only there. |
| `feature_window_mapping` | `FormWindowMapping` / `production_feature_config` | The candidate calls `production_feature_config(settings)` unchanged; the only added feature family is the appearance window, which the declaration names as a permitted input and which `test_the_appearance_window_is_the_only_addition_to_the_frozen_mapping` enumerates. |
| `shrinkage_weights` | `ProductionProjectionConfig.carry_over_rate_weight` | Passed through to `learned_points_per_90(carry_over_rate_weight=settings.carry_over_rate_weight)`; the fold config is rebuilt from `settings` with the same fields. |
| `opening_price_prior` | `backtest/production.py: _price_coefficient` | Reused as-is (`coefficient, prior_origin = _price_coefficient(visible, decision)`); `test_the_opening_price_prior_is_still_refit_on_completed_seasons` pins it. |
| `development_fold_set` | `walk_forward_decision_points` / 147 folds | Not in the diff; the regenerated export covers the same 147 fold ids as the control (pair preflight `pair_fold_policy` pass). |
| `baseline_control` | deterministic baseline @ `form_window_05_v1` | Not in the diff; regenerated control table hash unchanged (`1ed41f94…`). |
| `ridge_reference` | production benchmark Ridge reference | Not in the diff. |
| `optimization_contract` | `squadopt.optimization` | Not in the diff. |
| `budget_and_formation_constraints` | `OptimizationConfig` defaults | Not in the diff. |
| `promotion_gates` | `candidate_gate_spec.md`, benchmark gate policy | Not in the diff; benchmark configuration fingerprint reproduces byte for byte. |
| `evaluation_objective` | `single_gameweek_realized_squad_points_v1` | Named in the declaration and both manifests; the benchmark refuses a mismatch. |

**Verdict on step 4: the changed component is singular and every frozen component is
unchanged in the code.**

### The one observation (recorded, not blocking)

The frozen ladder scores the in-season rung wherever the rolling per-90 feature is
present. The candidate scores it where the per-90 feature is present **and every other
declared input is finite** (`modelled = in_season.notna() & complete`); a row that has
per-90 but lacks, say, an appearance feature falls to the carry-over rung instead. The
declaration states this deliberately ("a row is scored only where every declared input
is present"), and it is intrinsic to changing the rate — a rate model cannot score a
row without its inputs. But it is a small change of *which* rung a row lands on, so it
should be visible rather than assumed: the formal run's diagnostics should report the
`rate_source` counts (`learned_model` / `carry_over` / `unknown`) against the control's
(`in_season_history` / `cross_season_carry_over` / `no_record`), fold-aggregated. If the counts differ materially,
that is a fact about the candidate to record, not a reason to edit it — editing now
would be a new declaration.

## The (a)/(b) question: may the rate see the player's own scoring history?

The declaration flags that it keeps `points_per_90_last_6` as a rate input and asks
whether reading (a) — the frozen per-90 feature stays an input — or reading (b) — the
rate may not see the player's own scoring history at all — was intended.

**Reading (a) is confirmed.** Checklist item 1 was written on this side and it freezes
the *feature windows*; dropping the per-90 feature would change the feature mapping as
well as the rate, which is two changes. The declaration's own argument is the right one.
No v3 is required on this ground.

## learned-rate v1 → v2: clean enough to freeze?

PR #80 records that the first target construction (points divided by each row's own
minutes, unweighted) over-weighted short appearances, was caught by the recalibration
measurement (checklist item 11) as a bias of `-0.5154` against the control's
`-0.0055`, and was corrected by minutes-weighting the fit — after which the candidate
was reissued as `learned-rate-v2` with a new declaration fingerprint and the
predecessor named.

Assessment against Stage C step 9 (no post-hoc tuning against the gate):

- The defect is in target construction and is visible from training data alone (the
  weighted intercept lands at 3.79 where the true ratio of sums is 3.79; the unweighted
  one at 7.2). It is a correctness fix, not a tuning move.
- It was found by a **recalibration** measurement, not by the **gate**. The gate has
  never run against v1 or v2, so no gate response was available to iterate against.
- The reissue was handled the way the procedure asks: new version string, new
  fingerprint, predecessor named, nothing edited in place.

**This side's position: v2 is clean enough to freeze.** The one thing the record should
carry forward is that the v1 defect was surfaced by a candidate-versus-control
comparison — even though the fix needed no such comparison — so the reader of the
formal result knows the candidate has seen one measurement of itself before the gate.
The architecture/CI side's concurrence is still required for the freeze.

## Stage A status after this review

- Reviewed by the optimization/evaluation side: **done** (this document, `93a87d6`)
- Reviewed by the architecture/CI side: **pending**
- Fingerprints frozen: **pending** — computed and reproduced (see
  [issue43_handoff_acceptance.md](issue43_handoff_acceptance.md), item 17); the freeze
  is recorded when the third review lands
- Formal run (Stage B): **not executed**

Read the acceptance record's finding on candidate export reproducibility before the
freeze: it does not change the declaration, but it changes what the formal run's record
must name (the executing machine) for a second executor to interpret a difference.
