# Phase D Component Squad Calibration Preregistration

Status: frozen before the evaluator and before any binding component-squad calibration
measurement. The sampler-fidelity diagnostic is still pending; this document does not
authorize the binding run until that diagnostic is committed and reviewed.

## Question

For the Phase C component-model decisions, does the unadjusted Phase D component sampler
produce official-rules squad score distributions with acceptable location and lower-tail
frequency?

This is an internal calibration check. It does not promote a model, change the operational
control, tune a scenario parameter or publish a probability to a member.

## Frozen inputs

- The verified `phase_c_component_oof_v1` table and its decision roster.
- The Phase C candidate decision for every chronological OOF fold, optimized over the complete
  player pool before scenario eligibility is inspected.
- The component scenario sampler registered by
  `docs/phase_d_monte_carlo_v2_prereg.md`.
- The fixed-decision official-rules scorer and unadjusted distribution reading registered by
  `docs/phase_d_fixed_decision_scoring_prereg.md` and
  `docs/phase_d_fixed_decision_readout_prereg.md`.
- The realized official score for the same frozen decision and fold.

The scenario configuration is the existing `ScenarioConfig` default, stated explicitly:
`scenario_count=1000`, `deterministic_seed=0`, `min_history_folds=8`,
`min_player_observations=8`, `player_scale_shrinkage=10.0`,
`player_location_shrinkage=None`, and `double_gameweek_scale=1.0`.

No location shift, dispersion scale, residual recentering, winsorization, reweighting or
bootstrap correction is applied. If sampler fidelity cannot be verified, this run abstains;
these values are not changed to rescue it.

## Outcome-independent population

A fold is eligible only when all of the following were knowable before reading its outcome:

1. at least eight earlier folds contribute appearance-observed component residuals;
2. the complete squad decision was optimized before eligibility was checked;
3. all 15 selected players use `composition_route == "component_model"`; and
4. the fold is outside the locked 2025-26 holdout.

A read-only audit of the verified Phase C handoff found 147 OOF decisions. Nine are history
burn-in folds: `2021-22-gw02` through `2021-22-gw10`. The first usable fold is
`2021-22-gw11`. The burn-in contains nine rather than eight decisions because `2021-22-gw02`
has no appearance-observed component residual and therefore does not count as residual
history. Of the three decisions known to select a `direct_control` player, `2021-22-gw02`
and `2021-22-gw06` are already in burn-in; `2021-22-gw15` is the one additional abstention.

The binding population is therefore 137 folds, ending at `2024-25-gw38`. A runner that
observes a different population, first fold, last fold or direct-control abstention must stop
without producing a calibration verdict. No player may be removed before optimization to make
a fold eligible.

## Frozen readings and gates

For fold `t`, let `S_t^(j)` be the official-rules score of its frozen decision in scenario
`j`, and let `R_t` be its realized official score. Per-fold readings are:

```text
PIT_t = count(S_t^(j) <= R_t) / scenario_count
q10_t = linear tenth percentile of S_t
L_t   = 1[R_t < q10_t]
```

Equality is included in PIT and is not a lower-tail event. Across the 137 eligible folds:

- **S1 — location:** arithmetic mean of `PIT_t` must lie in `[0.43, 0.57]`, inclusive.
- **S2 — lower tail:** arithmetic mean of `L_t` must lie in `[0.04, 0.16]`, inclusive.

Both gates must pass for the result `calibrated_internal`. One or both measured failures yield
`failed`. Missing fidelity evidence, a population mismatch, invalid provenance, incomplete
realized scores or fewer than the frozen 137 folds yields `abstained`, not a pass or a zero.

The point estimates decide the gates. Per-season summaries are descriptive diagnostics only;
they cannot overturn the pooled result. No interval or parameter search is authorized here.

## Execution precondition

Before the single binding run, the sampler-fidelity diagnostic must be committed and reviewed.
It must measure, without tuning, appearance frequency, unconditional points and minutes means,
their conditional counterparts, residual-pool means and the one-minute floor engagement. A
missing or structurally invalid fidelity result causes abstention. It does not authorize a
shift or scale in this protocol.

The fidelity study is diagnostic-only and registers no numeric pass/fail threshold. Here,
"verified" therefore means its committed artifact loads under its own contract, names the
expected Phase C table and roster digests, records the frozen scenario configuration, excludes
the locked holdout and contains no non-finite or structurally contradictory reading. It does
not mean that a post-hoc numeric tolerance was met. The measured differences remain descriptive
and cannot be used to tune or rescue S1/S2.

## Acceptance checks before any binding run

- Synthetic fold readings reproduce S1 and S2 by hand.
- Gate bounds are inclusive.
- Duplicate fold identifiers, incomplete observations and non-finite values are rejected.
- The exact 137-fold population is enforced by the eventual binding runner.
- Inputs are not mutated.
- No 2025-26 path is read, listed or hashed.
- No member-facing payload or operational recommendation path changes.
