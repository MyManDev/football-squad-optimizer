# Measurement evidence validation

This document records the bounded validation correction made on 2026-09-09. It does
not revise historical measurement JSON, reopen a spent holdout, change a promotion
threshold, or activate a model or strategy. Passing this preflight checks the artifact's
declared governance; it does not independently prove that the declared actions occurred.

## Declarations by artifact kind

`squadopt.preflight.measurement.MEASUREMENT_DECLARATIONS` is the required-root-field
policy. The requirements follow the fields emitted by the existing producer for each
supported kind. This makes omission explicit without retroactively requiring a search
decision declaration from every descriptive report.

| Kind | `locked_holdout_accessed` | `automatic_promotion` | `recommendation_only` |
| --- | --- | --- | --- |
| `baseline_bayesopt` | required `false` | required `false` | required `true` |
| `policy_grid` | required `false` | required `false` | required `true` |
| `scenario_bayesopt` | required `false` | required `false` | required `true` |
| `risk_frontier` | required `false` | required `false` | required `true` |
| `multi_gw_rehearsal` | required `false` | optional `false` | required `true` |
| `scenario_audit` | required `false` | optional `false` | optional `true` |
| `control_uncertainty` | required `false` | optional `false` | optional `true` |
| `rotation_evidence` | required `false` | optional `false` | optional `true` |

Required declarations must appear at the artifact root. A valid nested declaration
cannot stand in for a missing root declaration. Every supplied declaration, including
one nested inside diagnostics, must have the exact boolean value above. `null`, strings,
numeric zero/one, arrays, empty mappings and contradictory nested values fail with a
named finding. An optional absent declaration is reported as **undeclared**; a passing
check in that case is not affirmative no-promotion or recommendation-only evidence.

The existing provenance, finite-number, digest-format and kind-specific required-field
checks remain. Unknown artifact kinds remain unsupported. This policy does not treat a
development evaluation season as unauthorized holdout access merely because another
contract uses the word holdout for its evaluation partition.

The committed baseline search, policy grid, risk frontier, scenario search and multi-GW
rehearsal reports remain accepted by the focused regression suite without rewriting their
bytes. Adding a new kind requires its producer and declaration policy to be reviewed
together; do not select an unrelated supported kind to obtain a passing result.

## Strategy Gate 2: one fold population

The strategy preregistration already requires the three direction frequencies to use the
same populations and pairing. The old `strategy_bench_v1` code instead averaged each
band over its own feasible folds. When feasibility differs, those rates do not describe
the same population and their ordering can be an artifact of exclusions.

New runs identify their output as `strategy_bench_v2`. For each horizon:

1. Start from the folds built for the declared development population.
2. Retain for Gate 2 only fold IDs with control, high-overlap and differential outcomes.
3. Compute all three wins-big frequencies on that single intersection.
4. Keep the existing direction rule, including its treatment of ties. The wins-big margin
   remains strictly greater than five points; bands, horizons, bootstrap and other gate
   thresholds do not change.
5. If the intersection is empty, all frequencies and the pass result are `null`; no zero
   frequency or affirmative result is fabricated.

`gate2_coverage` records eligible count, paired count and IDs, paired share, per-band
feasible counts, per-band excluded IDs and the union of exclusions. Control solves that
did not produce a scored row are included in these exclusions. Scored rows outside the
declared eligible IDs are rejected. A partial common population remains explicitly
partial; this correction invents no new coverage threshold and cannot support an
unqualified claim about excluded folds.

Gate 1 retains its high-overlap/differential pairing; Gate 3 retains each band's pairing
against control. No strategy registry evidence is promoted by running or changing this
script. Gate 4's existing repeated-control solve remains a determinism check; this change
does not claim it independently verifies a published baseline.

## History and next measurement

No old JSON report is recalculated or relabeled by this correction. The v1 Gate 2 reading
must be understood as using band-specific populations. A new binding reading requires
an explicitly recorded protocol correction and permitted data-access plan; the prior
one-rerun authorization in the historical preregistration is not silently renewed.
Preserve the old output and use a distinct output path for any separately authorized v2
measurement. No locked-holdout or current-season data is read by the focused tests.

Validation is covered by `test_measurement_preflight.py`, `test_strategy_bench_cli.py`
and `test_strategy_bench_gates.py`: missing/invalid/nested declarations, optional absence,
historical compatibility, a selection-bias counterexample, disjoint/empty populations,
coverage accounting, ties and the existing pre-load season refusal.
