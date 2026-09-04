# Pre-registration: why the squad distribution's lower tail is thin

Written 2026-08-30, before any number in this study has been computed.

The Phase 2 squad calibration ran once and recorded a **failed** verdict
(`shadow_calibration_squad.json`, sha256 `c690efd5…`). Its two squad gates disagree in
an informative way:

- **S1 passed.** Mean PIT 0.4921622, inside the pre-registered [0.43, 0.57]. After the
  frozen selection-optimism shift of −7.430702 points the realized squad score sits in
  the middle of its own scenario distribution.
- **S2 failed.** The realized score fell below that distribution's tenth percentile in
  **8 of 37** folds — a rate of 0.2162162 against the pre-registered [0.04, 0.16].

Centred, and too thin below. **This study does not try to fix that.** It asks why, on
development data, and it produces a classification and three descriptive readings — no
promotion, no candidate selection, no new model.

## What this study is not

It is a development diagnostic. It cannot promote anything, cannot change any gate,
threshold or seed, cannot modify the recorded Phase 2 artifact, and publishes no
probability, percentage or `P(...)` to any member-facing surface. It fits nothing: the
only thing that varies across its arms is one already-existing evaluation parameter.

## Research questions

**H1 — Global underdispersion.** Is the scenario distribution simply too narrow by a
single multiplicative factor? If one global scale on the spread puts both S1 and S2
inside their existing bands on validation data, the shortfall is a scale problem.

**H2 — Common gameweek shock (descriptive).** Does the squad's error move with the
direction of that gameweek's common residual? If the folds where the realized squad
score falls furthest below the scenario mean are the folds where every player
underperformed together, the common weekly component is under-represented rather than
the overall spread being uniformly small.

**H3 — Captain amplification (descriptive).** Do the below-q10 events concentrate in
folds where the captain's realized error is large and negative? The scoring policy
counts the captain twice, so a captain miss enters the squad score at double weight.

H2 and H3 are **descriptive**. They produce no model decision, no candidate and no
promotion in this study. They exist to say which of the two follow-up directions the
next pre-registration should take.

## Data split

| Population | Seasons | Role |
| --- | --- | --- |
| Screening | 2021-22, 2022-23 | Direction and consistency. Reported, does not decide. |
| Validation | 2023-24 | **The classification is decided here, and only here.** |
| Labelled development | 2024-25 | Its result was seen before this study was written. Sensitivity only: it may not select a candidate, may not support a promotion claim, and cannot change the classification. It is not a confirmation set and is never called one. |
| Locked confirmation holdout | 2025-26 | Never read, listed or fingerprinted, by this study or anything it calls. |

## The arms

The control is the Phase 2 setting, `dispersion_scale = 1.0`. The declared levels are
exactly:

```
1.00   1.15   1.30   1.45
```

No other level is measured. **No level may be added, removed or changed after any
result is seen**, and no optimizer, Bayesian or otherwise, proposes one. If four levels
turn out to bracket nothing, that is a result and the next study is a new
pre-registration.

## What is held identical across the arms

Every arm reuses the same folds, the same decisions, the same residual history and the
same scenario draws. Concretely:

1. The squad for a fold is optimized **once** and reused by all four arms.
2. The scenarios for a fold are generated **once**, at the pre-registered 200 draws and
   seed 11, and reused by all four arms. The arms differ only in the evaluation
   applied to that one matrix, so they share their random numbers by construction
   rather than by asserting it afterwards.
3. The frozen selection-optimism shift stays at the recorded **−7.430702271879578** for
   every arm and every season. It is not refitted per scale, for two reasons: the
   dispersion scale multiplies each scenario score's deviation from the raw mean and
   the location shift is added afterwards, so scaling cannot move the mean the shift
   corrects; and refitting per arm would add a second free parameter chosen after the
   failure was seen.
4. The residual history each fold sees is the one Phase 2 gave it: a development fold
   sees the folds of the chronological chain strictly before it, and a 2024-25 fold
   sees the history frozen at the end of 2023-24. The eight-fold burn-in of the third
   squad-gate amendment still applies to the development chain.
5. Model, projections, optimizer settings, `bench_weight`, the decision universe, the
   generator's shrinkage knobs, the quantile, the double-gameweek scale and the bands
   are all unchanged from the Phase 2 protocol.

## Control replay, fail-closed

The `1.00` arm on 2024-25 must reproduce the recorded artifact's S1 and S2 to within
`1e-12`. If it does not, the two runs are not the same measurement and this study stops
and writes nothing, rather than reporting a comparison whose baseline has drifted.

## Metrics

Per season and per scale, from the existing evaluator and nothing else:

- fold count;
- mean PIT;
- below-q10 count **and** rate — the count because at 37 folds the rate can only land
  on multiples of 1/37;
- mean scenario score and mean realized score;
- mean tail width, defined as the mean of (scenario mean score − scenario q10 score),
  which is what a dispersion scale is expected to move;
- a fold-level bootstrap interval from the canonical helper at the pre-registered 5000
  resamples, 90%, seed 0. **Diagnostic only**: no classification reads it.

No new composite score is invented.

A season with fewer than the pre-registered floor of 30 folds cannot decide anything and
is reported as such.

### H2 metric

From the residual export's own rows, through the canonical
`decompose_residual_components`, which the scenario generator already uses:

- per fold, the **common component** (that fold's mean player residual);
- per fold, the **squad gap**: realized squad score − scenario mean score, at the
  control arm;
- the sign-agreement rate and the Pearson correlation between those two series;
- the common component summarised separately over below-q10 folds and the rest.

The export carries `team_id`, so the same decomposition's **team component** is
available and is reported the same way. If a column the decomposition needs were
absent, this study would record *"team-shock diagnostic not measurable from this
artifact"* and measure nothing in its place. No join, no fabrication, no new pipeline.

This is a description of co-movement. It is not a causal claim and it is not a gate.

### H3 metric

From the existing decision and fold frames:

- per fold, the **captain's realized error**: the captain's realized points minus the
  captain's projected points;
- that error summarised over below-q10 folds and the rest.

A fold whose decision names no captain is recorded as **missing**, never as zero. If
isolating the captain required changing the optimization or scoring contract, this
study would record *"current artifact does not isolate captain contribution"* and
measure nothing in its place — but it does not: `OptimizationResult` names the captain
and the scoring policy that counts it twice is unchanged.

## Decision rule

This study performs no promotion. It emits exactly one of three classifications,
decided on **2023-24 validation only**:

- **`scale_sufficient_candidate`** — at least one declared scale keeps *both* S1 and S2
  inside their existing pre-registered bands on 2023-24.
- **`scale_not_sufficient`** — no declared scale satisfies both gates together on
  2023-24.
- **`diagnostic_inconclusive`** — the validation season carries fewer folds than the
  floor, or a required input is missing, so neither of the above can be stated.

If more than one scale qualifies, this study **does not pick a winner** and does not
promote the smallest. It reports the eligible set, and choosing one from it is the
subject of a separate pre-registration. The 2024-25 numbers are shown beside the
classification as sensitivity and cannot change it.

## What a result unlocks

Nothing operational. A `scale_sufficient_candidate` unlocks the right to write a
candidate-selection pre-registration; a `scale_not_sufficient` says the next Phase 2
study is about the common weekly shock rather than about a scale. In both cases the
2025-26 holdout stays closed.
