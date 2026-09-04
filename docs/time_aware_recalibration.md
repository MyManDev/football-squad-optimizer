# Time-Aware Calendar Recalibration — the #38 study

The chronological recalibration study from `docs/recalibration_runbook.md` step 3, run on
the matched calendar-blind control and calendar-aware candidate residual exports. The
tables stay local; this document is the committed record.

**This is recalibration evidence. It does not promote a prediction model, change the
operational control, or change the optimizer,** and it is not the #43 gate — that
candidate still passes or fails its own frozen single-gameweek gate independently of
anything here.

## Inputs

| | Reference | Candidate |
| --- | --- | --- |
| Label | `calendar_blind_baseline` | `calendar_aware_learned_rate` |
| Model | `deterministic_baseline@form_window_05_v1` | `squadopt-learned-rate@learned-rate-v2` |
| Table SHA-256 | `1ed41f94f245b06d012293a895cdee755a5b1803cb19bcc3795e4a414767a22f` | `424b0d76f37bab4ca0c6f6850f8444e95aa660ef69b91a2a8fb017d434fd367f` |

Both produced at repository commit `8c0ff540a467`, dataset snapshot
`vaastav-fpl@8c97b2adb123863c3dd581e730f1360e89815ac2`, 147 folds and 101,447 rows each.

Preflight before measurement: candidate 31/31, control 31/31, pair 10/10, zero findings.

The control table has now been regenerated at three different repository commits and its
SHA-256 has not moved. That is a stronger reproducibility claim than the runbook asks for,
and it is the reason the pair could be rebuilt at the merged commit without renegotiating
anything.

| Fingerprint | Value |
| --- | --- |
| Measurement | `af5ad1582f47b1847599151e9490393966b0690e6ac9c23c70066ed976071305` |
| Configuration | `0e01ee3cea125967b752469cf02eb23ac8879a908e30fdf04214f88060f3deb2` |
| Study | `4284585c3aa22d7eba327025d6aab142f12f99c92684e8650c107597b67c74a9` |

All three are required by the runbook's step-3 review list, and only the last of them
reached this document when it was first merged. See the note at the end.

## Chronological split

| Slice | Folds | Range |
| --- | ---: | --- |
| Scale training | 58 | `2021-22-gw02` … `2022-23-gw23` |
| Conformal calibration | 44 | `2022-23-gw24` … `2023-24-gw30` |
| Evaluation | 45 | `2023-24-gw31` … `2024-25-gw38` |

Verified rather than assumed: the three sets intersect in zero folds, their union is
exactly the 147-fold population, and each begins where the previous ends.
`evaluation_refit` is `false` — nothing is fitted on the slice it is scored on.

## Held-out conformal coverage and width

Nominal level 0.90.

| Fixture group | Rows | Reference coverage | Candidate coverage | Reference width | Candidate width | Width delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 33,103 | 0.8997 | 0.8989 | 6.0710 | 5.6314 | **−0.4396** |
| single | 32,083 | 0.9019 | 0.9019 | 6.0668 | 5.6279 | −0.4389 |
| double_plus | 1,020 | 0.8304 | 0.8039 | 6.2017 | 5.7417 | −0.4600 |

**The headline.** On single gameweeks the two regimes hold identical coverage — 0.9019
each, on the nominal 0.90 — while the candidate's intervals are 7.2% narrower. Tighter
intervals at unchanged coverage is the result this study was run to look for.

**The qualification, which matters more than the headline.** On double gameweeks *both*
regimes undercover: 0.8304 and 0.8039 against a nominal 0.90. The candidate is the worse
of the two by 0.0265, because its intervals are narrower everywhere and a narrower
interval on an already-undercovered group undercovers further.

So the calendar-aware regime improves the average and leaves the hardest group unfixed. It
would be easy to read the overall row as "coverage held" and miss that; the overall row
holds because 97% of the population is single gameweeks. 1,020 rows is a small group and
is reported as small — not padded, not merged into the single group, and not declared
conclusive.

## Scenario residual decomposition

| Component | Reference SD | Candidate SD | Delta |
| --- | ---: | ---: | ---: |
| Common gameweek | 0.1463 | 0.0715 | −0.0748 |
| Team-gameweek | 0.6616 | 0.5869 | −0.0747 |
| Player idiosyncratic | 2.1854 | 2.0942 | −0.0913 |

All three shrink. The common-gameweek component halves, which is the component a calendar
term should touch: a shock shared by every player in a gameweek is partly the calendar
itself, and a regime that sees the calendar should leave less of it unexplained.

## Double-gameweek player scales

828 players with double-gameweek history carry a player-adaptive scale under each regime.
The deltas are predominantly negative — the candidate needs less inflation for the players
whose variance the calendar was previously explaining — with a minority positive.

## Limits the study states about itself

Recorded here rather than paraphrased, because two of them bound how far the coverage
result above can be read:

- the report is development recalibration evidence, not model-promotion evidence;
- opening-gameweek uncertainty is not inferred from later-gameweek residuals;
- conformal intervals are marginal, and their interpretation still depends on
  exchangeability — which the double-gameweek undercoverage above is itself a symptom of,
  since a double gameweek is not exchangeable with a single one;
- scenario component spreads are re-estimated empirically, and no parametric joint
  distribution is claimed.

## What this permits

Per runbook step 4:

- It permits updating uncertainty and scenario calibration evidence.
- It does **not** promote a prediction model, change the operational control, or change
  the optimizer.
- It does not touch the #43 gate.

For live GW1 risk, `opening_gameweeks_included` is `false` in both manifests, so the
correct state remains structured `unavailable`. `opening_gameweek_uncertainty_inferred` is
`false` in the study's own diagnostics: gameweek-two-and-later residuals are not reused for
an opening gameweek. See the [GW1 evidence blocker
report](gw1_blocker_report_2021-2026.md).

## Reproduction

```powershell
.venv\Scripts\python -m scripts.export_candidate_residuals --candidate learned
.venv\Scripts\python -m scripts.run_calendar_recalibration `
  --reference-residuals artifacts/residuals/control_residuals.csv `
  --reference-manifest artifacts/residuals/control_residuals.manifest.json `
  --candidate-residuals artifacts/residuals/learned_candidate_residuals.csv `
  --candidate-manifest artifacts/residuals/learned_candidate_residuals.manifest.json `
  --candidate-label calendar_aware_learned_rate `
  --time-aware `
  --scale-training-fraction 0.40 `
  --conformal-calibration-fraction 0.30 `
  --confidence-level 0.90
```

Produced by the prediction side as the #38 handoff. Whether the calibration is updated on
this evidence is the uncertainty/scenario owner's decision, not this document's.

## Note on how this document was first merged

PR #82 merged an incomplete version of this record, and the gap is worth naming rather than
patching quietly.

The branch was pushed, the fingerprint table and the limits section were committed *after*
that push, and the pull request was opened without them. The commit never reached
`develop`. So the merged document carried one fingerprint of the three the runbook requires,
and no limits section — while **PR #82's own body listed all three fingerprints**, which
means the pull request claimed something the merged file did not contain.

Nothing measured changed. The numbers here are from the same run and the same three
fingerprints identify it. What was missing was the record, which is the part this whole
procedure exists to protect, so it is recorded rather than silently corrected.

The habit that caused it: opening a pull request without first checking that the pushed tip
matches local `HEAD`. `git log origin/<branch>..<branch>` answers that in one line.
