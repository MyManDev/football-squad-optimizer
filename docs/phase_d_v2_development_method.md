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

## The sampler-fidelity record

The protocol's precondition is a committed sampler-fidelity diagnostic, and the frozen one
describes the v1 export under the foundation sampler. `scripts.measure_component_fidelity
--phase-c-contract development_v2` produces the matching record for this path: the same five
differences by the same method, read from the same reference through the development reader
and pinned to its three digests, drawn on the same declared candidate sampler, written under
the distinct contract `phase_d_component_fidelity_development_v2`. It never writes the frozen
v1 artifact path, and the v1 diagnostic refuses every option that belongs to this path.

Two clauses of the frozen documents are deliberately inverted here, and only here. The
fidelity pre-registration says the locked 2025-26 holdout "is not read, listed or hashed" and
requires `locked_holdout_read: false`; the calibration pre-registration folds the same
exclusion into what "verified" means. A v2 record is measured over the reference's whole
five-season population and therefore carries `locked_holdout_read: true` with a non-zero
`locked_holdout_rows_present`. That is the same development-scope decision the Phase C v2
contract already made, not a relaxation of either frozen document: both keep governing the v1
path, which still refuses that season outright.

The record itself is a measurement output. It is produced locally beside the other Phase D v2
measurements and is not committed, so the run's verdict rests on a verified but unreviewed
artifact — weaker than the v1 path, where the diagnostic is committed and reviewed. A verdict
read this way is development evidence and nothing more.

`--fidelity` then hands that record to the calibration run, which verifies before it measures:
the contract; the diagnostic-only flags; the configuration, field by field, against this run's
own `ScenarioConfig`; the sampler contract, fraction and minimum rows against this run's own
sampler; the three artifact digests, the model, the weighting, the four contract versions and
the Phase C producer commit against the handoff; and the record's own fold bookkeeping. Once
the population is computed, the record's measured and excluded folds must equal this run's
history-eligible and burn-in folds, which are decided by different code from the same inputs,
and every fold this run measures must be covered by the record.

The two studies do not share an observation. The diagnostic's unit is one (fold, player) pair
over every component row of a fold; this run's unit is one frozen fifteen-player decision per
fold. So a verified record answers only "was this sampler, on this reference, measured over
these folds" — never anything numeric about the squad distributions, and never whether there
are enough folds to read.

## Readings and status

The development reading is taken with the registered candidate sampler,
`ConditionalResidualConfig(fraction=0.15, minimum_rows=30)`
(`component_scenario_conditional_residual_v1`), passed on the command line exactly as the
Phase D candidate measurement passed it; the report's `candidate` block records it and names
the development contract as its reference. Per-fold readings are the existing PIT, q10 and
lower-tail indicator from the official scorer. The inherited gates are reported beside the
readings as a development observation (mean PIT against `[0.43, 0.57]`, lower-tail rate
against `[0.04, 0.16]`). Without a verified fidelity record the protocol's verdict abstains
(`sampler_fidelity_not_verified`); with one it is evaluated against those inherited bounds and
may read `calibrated_internal` or `failed`. Either way it is a development reading on seen
folds, not the binding verdict.

The population a verdict is read against is declared before any outcome: every history-eligible
fold except the direct-control abstentions the pre-registration already excludes. A fold that
then fails to solve or loses its realized score is a population mismatch the evaluator sees,
never a smaller denominator. A `--folds` run names an operator's own subset, which is not that
population, so it produces no verdict however many folds it names. Nothing in the sampler, the
scenario configuration, the solver profile or the gates is changed to alter any of this.
