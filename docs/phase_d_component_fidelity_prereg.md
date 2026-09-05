# Phase D — component sampler fidelity, pre-registration

Status: **frozen before the runner and before any measurement.** This document is committed
ahead of the code it describes, so the metrics below cannot be chosen after seeing an output.

This is a **diagnostic**. It registers no threshold, no pass/fail condition and no promotion
gate. It measures how the component sampler's draws relate to the Phase C component predictions
they are built from, records whatever comes out, and changes nothing in response. There is no
calibration, no shift, no dispersion adjustment and no parameter search here.

## 1. Why exact agreement is not expected

The point that makes this a measurement rather than a check. The sampler draws paired residuals
empirically from prior folds, and an empirical residual pool is **not required to have mean
zero**. Therefore

```text
E[Y_i] = p_i * (mu_points_i + E[eps_points])
```

and equality with `p_i * mu_points_i` holds only when `E[eps_points]` happens to be zero over the
pool — and, under the one-source-fold rule, over the particular fold each scenario drew from.

Minutes carry two further reasons. They are clipped above at `90 * fixture_count`, and since the
appearance-observability amendment they are floored at `1` for an appearance. Both bounds move a
mean, so the conditional minutes mean need not equal `mu_minutes_i` either.

**This study quantifies those gaps. It does not drive them to zero.** A non-zero difference is a
result, not a defect, and nothing about the seed, the scenario count, the residual pool, the
clipping or the floor is adjusted because of what is measured.

## 2. Population

- Development seasons only: **2021-22, 2022-23, 2023-24, 2024-25**.
- The locked **2025-26** holdout is not read, listed or hashed. The Phase C artifact declares
  `development_seasons` without it and `locked_holdout_read: false`; the runner additionally
  refuses outright if any row carries that season, and
  `ComponentScenarioProvenance` refuses it independently.
- Only rows with `composition_route == component_model` enter the measurement.
- `direct_control` rows are **excluded at input construction** and their count is reported per
  fold and in total. No zero is substituted and no component prediction is invented for them.
  This is also what keeps the sampler's fail-closed refusal from firing: after the filter, no
  control row reaches it.

## 3. Configuration — recorded, not chosen

The canonical `ScenarioConfig()` defaults are used as they stand. No new number is selected.

```text
scenario_count      = 1000
deterministic_seed  = 0
min_history_folds   = 8
```

All three are written into the artifact. `min_history_folds = 8` is passed **explicitly** to the
residual pool as well, rather than leaving that function's own default of `1`, so one threshold
governs both the config and the pool and the artifact has a single number to explain.

That choice determines eligibility. Of 147 folds, **138 are eligible**, first `2021-22-gw11`. The
9 excluded folds are `2021-22-gw02`, which has no `component_model` row at all — the artifact's
own `folds_refused_for_thin_history`, so every row there took the control route — plus 8 folds
with fewer than 8 prior residual folds. The artifact lists each exclusion with its reason.

## 4. Leakage rule

Unchanged from the foundation's own pre-registration and restated because this study depends on
it: each fold draws residuals only from folds **strictly before** it, one source fold is chosen
per scenario, and every player cell in that scenario is drawn from a row inside that fold.

## 5. The metrics

Five differences, each `sampled − predicted`, so a positive number means the sampler produced
more than the component prediction.

| | Quantity | Comparison target |
| --- | --- | --- |
| **A** | sampled appearance frequency | `appearance_probability` |
| **B** | `scenario_points` mean | `appearance_probability * raw_expected_points_if_appearance` |
| **C** | `sampled_minutes` mean | `appearance_probability * expected_minutes_if_appearance` |
| **D** | `sampled_minutes` mean over cells where `sampled_appearance` is true | `expected_minutes_if_appearance` |
| **E** | `scenario_points` mean over cells where `sampled_appearance` is true | `raw_expected_points_if_appearance` |

B, C and E use the **raw** conditional point column, not `control_expected_points`, because the
latter is bounded below at zero by the export's public-points rule and this study must not
inherit that clip into a distributional comparison.

For each metric the artifact records:

- pooled mean signed difference;
- pooled mean absolute difference;
- a fold-level summary of the per-fold mean differences;
- the sample count behind it;
- the `direct_control` rows excluded;
- the blank-fixture count;
- the floor-engaged cell count and rate.

Per-fold records are retained alongside the pooled figures, not replaced by the summary, because
this measurement is run once and a later question about drift by season or fold has to be
answerable from the file rather than by a re-run.

### Two stated limitations of the metrics themselves

**Floor engagement is a proxy.** The sampler does not expose the pre-clip minute value, so an
engaged floor is counted as a cell where the appearance is true and `sampled_minutes` equals
exactly `1.0`. That is an **upper bound**: it also catches a draw that legitimately lands on
`1.0`, which is possible though vanishingly rare with float residuals. The proxy is registered
here rather than fixed, because recovering the pre-clip value would mean changing production
code for a diagnostic.

**The blank-fixture count is expected to be zero.** Every `component_model` row in the
development artifact carries `fixture_count` of 1 or 2, so no blank-fixture cell exists to
measure. It is still reported, as a zero that was checked rather than a case that was forgotten.

## 6. Procedure

Run **once**, after this document is committed and after every quality gate is green. The runner
refuses a dirty working tree before reading anything, so the artifact cannot record a commit that
does not describe the code that produced it.

No re-run. No adjustment after seeing the numbers. If the result is uninteresting or unflattering
it is recorded as it is.

## 7. What this is not

- Not a promotion, a calibration or a tuning step.
- No threshold, gate, bootstrap or confidence interval is registered.
- No residual centering, location shift or dispersion scale is introduced.
- No new model, model registry, residual abstraction or calibration framework.
- No probability is published to a user; the artifact is internal.
- No parameter sweep, and no second run under different settings.
- The fixed-squad decision-level work — official autosub, bench and vice-captain scoring, squad
  mean/q10/PIT, and its own fold-eligibility and abstention rules — is a separate effort and is
  not measured, reimplemented or reported here. Its fold counts are decision-level and
  squad-scoped; the counts in this document are player-level over every `component_model` row,
  so the two are different quantities and must not be read as one.
