# Phase D Fixed-Decision Distribution Readout Preregistration

Status: frozen before implementation. This document authorizes no binding measurement,
calibration correction, model promotion or live publication.

## Question

Given one squad decision frozen before outcomes and scored under official autosub, bench,
vice-captain and captain rules across one component scenario draw, what are the canonical
internal summaries of its score distribution?

This step standardizes the reading only. It does not claim that the distribution is calibrated.

## Frozen reading

The input is one validated `ComponentDecisionScoringResult`. Scenario scores remain in their
recorded order and are not shifted, scaled, winsorized or reweighted.

The result records:

- scenario count;
- arithmetic mean score;
- population standard deviation (`ddof=0`);
- the tenth percentile, using NumPy's `linear` quantile interpolation;
- the scenario and component fingerprints and the decision-scoring contract version.

When an observed official score is supplied, the same result additionally records:

- PIT as the fraction of scenario scores less than or equal to the observed score; and
- whether the observed score is strictly below the scenario tenth percentile.

The inclusive PIT and strict lower-tail comparison are the existing S1/S2 conventions used by
the recorded squad-calibration studies. This step does not create alternative definitions.
An absent observation stays absent; it is not represented as zero.

## Direct-control eligibility for a future measurement

The Phase C decision is first optimized over its complete player pool. No player may be removed
from that pool to make component sampling possible. After the decision is frozen, all 15 selected
players must have `composition_route == "component_model"`. If any selected player uses
`direct_control`, that fold abstains because the sampler has no bound conditional distribution
for that player. A direct-control value must not be invented, sampled as zero or replaced by an
unrecorded fallback.

A read-only feasibility audit of the verified Phase C development handoff found 144 eligible
decisions among 147. The three outcome-independent abstentions are:

- `2021-22-gw02`: all 15 squad players, the starting XI and captain use direct control;
- `2021-22-gw06`: one bench player uses direct control; and
- `2021-22-gw15`: one bench player uses direct control.

These counts describe coverage, not model quality. This document does not authorize the future
S1/S2 run; its population, scenario configuration, provenance and gates must be frozen before
that measurement.

## Explicit non-goals

- no scenario generation or residual-pool change;
- no location shift, dispersion scale or tail correction;
- no mean-fidelity gate, which belongs to the sampler diagnostic;
- no CVaR objective or scenario-aware re-optimization;
- no bootstrap interval or parameter search;
- no member-facing probability or live-default change;
- no locked 2025-26 holdout access.

## Acceptance checks

- A small hand-calculated score vector reproduces mean, population standard deviation and q10.
- Equality with q10 is not classified as below q10.
- PIT includes scenario scores equal to the observation.
- Missing and non-finite observations are distinguished and rejected appropriately.
- Input scores and caller-owned objects are not mutated.
- Scenario and component identities are carried through unchanged.
