# Phase D v2 development method: reading the Phase C v2 equal-weight reference

This note records how the Phase D component-squad calibration reads the Phase C v2
development handoff. It is a development reading under the existing preregistered protocol
(`docs/phase_d_component_squad_calibration_prereg.md`); it is not the binding verdict, it
does not pin a production model, and it starts no Phase E run.

## The reference

The input is the Phase C v2 **equal-weight** arm (`phase_c_component_oof_development_v2`,
model `phase_c_control_components_v1`, weighting `equal_weights_v1`), fixed as the reference
for Phase D development after the declared C comparison returned `no_selection`. Fixing it
is a working decision, not an acceptance: the binding Phase D verdict stays `failed`, the
production pin stays empty and E4 stays closed.

A run names the reference by its three artifact digests on the command line and is refused
if the handoff it reads differs in table, roster or manifest digest, in weighting, or in
model version. The season-weighted arm shares the reference's roster digest and cannot pass
these checks.

## How the runner changes

`scripts.run_component_squad_calibration --phase-c-contract development_v2` is the only way
into this path; the default `v1` binding path is unchanged, including its required fidelity
artifact and its frozen 137-fold population.

- The handoff is read through `read_phase_c_component_handoff(...,
  development_contract=...)`, and the decision folds are prepared through
  `prepare_phase_c_component_folds(..., development_contract=...)`; both refuse a
  development artifact unless the caller names the contract.
- The component sampler admits a 2025-26 decision only when the scenario provenance carries
  the development contract; the contract then enters the draw's component fingerprint and
  diagnostics, so a development draw can never pass for a frozen one.
- The population is computed from the handoff under the preregistration's eligibility rule
  rather than asserted: a fold is history-eligible once at least `min_history_folds` earlier
  folds contribute an appearance-observed component residual; a fold whose full-pool decision
  selects a `direct_control` player abstains; unsolved or unscored folds are listed, not
  dropped. `--folds` restricts the measured folds for a pilot while eligibility is still
  computed for the whole handoff.
- Every fold's control decision uses the walk-forward panel visible before it, the residual
  pool uses only earlier folds, and the realized official score is read only at evaluation.
- The report carries the distinct contract `phase_d_component_squad_calibration_development_v2`,
  `binding: false`, `development_only: true`, an honest `locked_holdout_accessed: true`, the
  pinned digests, the fixed solver profile, the sampler record and, per fold, the complete
  decision identity (squad, starting eleven, captain, bench order) beside the readings.

## Readings and status

The development reading is taken with the registered candidate sampler,
`ConditionalResidualConfig(fraction=0.15, minimum_rows=30)`
(`component_scenario_conditional_residual_v1`), passed on the command line exactly as the
Phase D candidate measurement passed it; the report's `candidate` block records it and names
the development contract as its reference. Per-fold readings are the existing PIT, q10 and
lower-tail indicator from the official scorer. The inherited gates are reported beside the
readings as a development observation (mean PIT against `[0.43, 0.57]`, lower-tail rate
against `[0.04, 0.16]`). No sampler-fidelity artifact exists for the v2 handoff, so the
protocol's verdict abstains (`sampler_fidelity_not_verified`) on a full run and is not
computed at all on a pilot with fewer than the minimum folds. Nothing in the sampler, the
scenario configuration, the solver profile or the gates is changed to alter that reading.
