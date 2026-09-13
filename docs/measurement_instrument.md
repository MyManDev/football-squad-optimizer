# Measurement instrument

Issue #525 is a measurement study. The run uses the existing Phase C component-base
versus historical ridge-control comparison in `phase_c_component_evaluation.json`,
with official scoring and its complete development population. Neither the point
model nor the promotion rule changes. No raw holdout-season file is read.

## Fixed analysis

The verified Phase C handoff and existing control projection builder supply
covariates for the complete, ordered fold population of the recorded comparison.
Input hashes, scoring policy, finite scores and paired-difference arithmetic are
validated. Recorded scores are never replaced with new optimization results.
The historical comparison includes time-limited FEASIBLE solutions; an initial
attempt to require optimal replay refused at 2021-22-gw04. Rerunning that solver
cannot establish identity of the original decisions. No correlations were measured
in that refused attempt.

The fixed covariates for the completed study are the component pool's mean and
total projected points and the control pool's total projected points. These need
no reconstructed XI. Direct-control fallback rows use the existing control builder.
No target column enters the covariates; the handoff independently checks outcome
alignment. Historical selected-XI projections are excluded because the frozen
selected identities needed for them are absent from the comparison record.

These inherit the handoff's structural pre-decision contract. Historical deadline
timestamps are absent; no deadline is invented from kickoff. The source manifest
checks strictly earlier training folds and shifted features. Same-week realised
ownership-template scores, the game's average and realised points scale are
excluded because they are unavailable at the decision. Historical ownership timing
is also unverified. Missing alternatives are reported, not substituted silently.

For each covariate, report its correlation with the paired difference, fitted
coefficient, residual variance ratio and conditional residual floor. Report both
an IID normal 90% interval half-width and an IID normal two-sided MDE at alpha 0.05,
power 0.8. These are different quantities. Weeks and overlapping squads can violate
the independence approximation; these descriptive figures do not certify a new gate.

There is a necessary qualification to sample-centering. With the covariate mean
estimated on these same folds, the adjusted sample mean is algebraically identical
to the raw mean, including when the complete procedure is resampled. A smaller
row-residual standard deviation does not by itself improve the unconditional
precision of that estimator. The report therefore keeps the unconditional floor
unchanged. A justified external covariate expectation or a separately specified
estimand would be needed before claiming a precision gain. The reference method is
[Deng et al., WSDM 2013](https://ai.stanford.edu/~ronnyk/2013-02CUPEDImprovingSensitivityOfControlledExperiments.pdf).

An additional expanding-history diagnostic fits its coefficient and center only
on earlier folds, starting after a fixed 24-fold history. It reports the raw and
adjusted matched population separately. It is neither an unbiased-effect claim nor
a candidate selection rule; the largest observed correlation is descriptive.

## Error decomposition and availability

The existing scoreboard publisher supplies the four error columns. The command
builds a private preview under `.pt`, reads its system rows and records the exact
same diagnostics. It does not fill legacy vice, bench order or projected minutes.
Unsettled measurements and absent projections remain null. Existing public
components and their language guard are retained.

All verified capture directories in the named source root are considered. Forecasts
use the explicitly marked next event, strictly before its published deadline.
Outcomes use the latest same-season, same-week checked and finished capture after
that deadline. Persistent player codes join the records. A missing player outcome
is unknown; zero observed minutes is a measured nonappearance.

The primary table uses the latest forecast per player/week. Per-capture tables are
also retained, without pooling repeated captures as independent players. Both
status and stated value are tabulated, with null kept as its own category. Without
settled pairs, the table contains forecast coverage and null realised rates. It
cannot support a calibration conclusion until a suitable result capture exists.

## Reproduction

From the measurement checkout, with the original local inputs available:

```powershell
$env:PYTHONPATH="$PWD/src;$PWD"
../../../.venv/Scripts/python.exe -m scripts.measure_instrument `
  --source-root ../../.. `
  --handoff-dir ../../../.codex-tmp/phase-e-frozen-inputs `
  --preview-root .pt/instrument-preview `
  --output docs/measurement_instrument.json
```

The JSON record includes source hashes, repository revision and dependency versions.
Inputs are hashed before and after the run; changed bytes refuse publication. The
existing atomic create-once writer refuses to overwrite a different measurement.
The exact input snapshot inventory must be retained for a historical replay.
Choose a fresh preview directory on every run: a retained old scoreboard is not an
input to this measurement. Source changes must be committed before the run and
the revision must remain unchanged through it. To compare a new replay, write to a
new internal output file and compare the measurement sections; revision and wall
clock metadata describe the new execution.
