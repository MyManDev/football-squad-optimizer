# Candidate Runtime

Checklist item 15: per-candidate wall time over the 147 development folds.

- Machine: Windows-10-10.0.26200-SP0, Intel64 Family 6 Model 141 Stepping 1, GenuineIntel
- Python: 3.11.0
- Stopping rule: every one of the 147 development folds is projected; no early exit, no solver
- Archive load (shared, once): 7.7 s

| Regime | Wall time | Folds | Rows | Seconds per fold |
| --- | ---: | ---: | ---: | ---: |
| `learned` | 590.3 s | 147 | 101,447 | 4.02 |
| `control` | 11.7 s | 147 | 101,447 | 0.08 |

## Reading

Wall time on an idle machine, each regime timed on its own. The archive load is shared across regimes and reported separately so it is not counted twice.

The stopping rule is worth stating precisely because the benchmark has a different one. This export never reaches CP-SAT — it is projection only — so the deterministic solver budget that bounds a formal gate run does not apply here, and quoting it would describe a stage that does not run.

Informational. It gates nothing and is not gate evidence.

## The gap between the regimes

The learned candidate costs about fifty times the control. The control reuses a cached per-season carry-over and reads a rolling feature; the candidate rebuilds the current season's features with the fixture join at every fold and refits a ridge system on an expanding training slice that reaches roughly a hundred thousand rows by the last fold.

That is where the time goes by construction, not a profile. Nobody has profiled it, so the attribution is a reading of the design rather than a measurement, and it is written that way on purpose.

The number that matters for planning a search: at this cost one candidate evaluation is minutes, not seconds, so a thirty-evaluation sweep over this regime is hours. The Bayesian evaluator runs the control path rather than this one, so it is not bound by this figure.

## Reproduction

```powershell
.venv\Scripts\python -m scripts.measure_candidate_runtime
```
