# Measurement instrument

Issue #525 is a measurement study. The run uses the existing Phase C component-base
versus historical ridge-control comparison in `phase_c_component_evaluation.json`,
with official scoring and its complete development population. Neither the point
model nor the promotion rule changes. No raw holdout-season file is read.

## Fixed analysis

The verified Phase C handoff and the existing control projection builder reproduce
both scores in each recorded fold before any comparison. A different score, input
hash, fold population or scoring policy refuses the run. The candidate covariates
are fixed before measurement: projected XI plus captain for each arm, and the
component pool's total projected points. No target column enters selection.

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
