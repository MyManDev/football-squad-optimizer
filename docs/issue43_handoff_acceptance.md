# Issue #43 Handoff — Acceptance Record (optimization/evaluation side)

The prediction-side handoff for the learned-rate candidate (PR #80, follow-ups #82/#89)
checked against every item of [handoff_acceptance_checklist.md](handoff_acceptance_checklist.md).
Where the checklist names a command, the command was **re-run on this side's machine**
at the merged commit rather than read from the delivering side's record, because the
value of an acceptance pass is that it is independent.

- Repository commit: `93a87d6291c727d51a35ad7b84fced0719d3dcca` (`develop`, 2026-08-16)
- Dataset snapshot: `vaastav-fpl@8c97b2adb123863c3dd581e730f1360e89815ac2`
- Machine: Windows 11, Python 3.13, the repository `.venv`; all runs from a clean tree
- Reference records: [candidate_residual_export.md](candidate_residual_export.md),
  [time_aware_recalibration.md](time_aware_recalibration.md),
  [issue43_candidate_declaration.md](issue43_candidate_declaration.md)

## Verdict

**Accepted with one recorded finding — since resolved.** Every applicable checklist item
passes. Item 15 (per-candidate runtime) was delivered after this record was first written
(PR #95). The recorded finding (item 9/10, below) was not a checklist failure — the
preflight exits 0 — but it changed what a `table_sha256` could be used to claim; the
prediction side measured it and took the fix in PR #94 (see the follow-up note at the
end).

## Item by item

| # | Item | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Learned-rate candidate definition | PASS | Reviewed in [issue43_stage_a_review.md](issue43_stage_a_review.md): the changed component is `expected_points_rate` alone; every listed frozen component is reached through the existing code, not copied. |
| 2 | Candidate builder implementation | PASS | `src/squadopt/prediction/learned_rate.py`, `src/squadopt/backtest/learned_candidate.py`; 105 synthetic tests across `test_learned_rate.py` (26), `test_learned_candidate.py` (20), `test_candidate_declaration.py` (19), `test_candidate_residuals.py` (20), `test_policy_evaluation.py` (20). Four gates on the merged tree: item 16. |
| 3 | Model name and version | PASS | `squadopt-learned-rate` / `learned-rate-v2` identical in the declaration JSON, the regenerated candidate manifest, and (by construction, `build_learned_candidate_snapshot`) the `PredictionSnapshot` provenance. |
| 4 | Feature contract version | PASS | `learned-rate-calendar-appearance-v1` in declaration and manifest; the mapping test (item 7) shows it is `form_window_v1` plus the appearance window only. |
| 5 | Training contract version | PASS | `expanding_window_minutes_weighted_ridge_rate_v1` in the candidate manifest; control carries `deterministic_baseline_no_training_v1`. Named in the declaration. |
| 6 | Candidate `PredictionSnapshot` provenance | PASS | `learned_candidate.py` sets model/feature identity from the module constants and `training_cutoff` / `training_data_fingerprint` from the training slice; `test_the_snapshot_carries_the_learned_rate_identity` pins it. |
| 7 | `form_window_v1` mapping verification | PASS | `test_the_candidate_applies_the_frozen_mapping_plus_the_appearance_window` compares field by field; `test_the_appearance_window_is_the_only_addition_to_the_frozen_mapping` enumerates the dataclass so a new field cannot slip past. |
| 8 | Calendar-blind residual export | PASS | Regenerated at `93a87d6`: 147 folds, 101,447 rows, preflight **31/31**; `table_sha256 = 1ed41f94f245b06d012293a895cdee755a5b1803cb19bcc3795e4a414767a22f` — **identical** to the delivering side's value, now stable across four commits and two machines. |
| 9 | Calendar-aware residual export | PASS (with finding) | Regenerated at `93a87d6`: 147 folds, 101,447 rows, preflight **31/31**, pair preflight **10/10**. `table_sha256 = b5c5e9cae8a0b19554c39778811cc180ff1da32b49b6086b6de5a3a3c3160ca6` — **differs** from the delivering side's `424b0d76…`. See the finding below. |
| 10 | Two manifests | PASS | Both manifests regenerated and retained locally under `artifacts/residuals-verify/` with the preflight report; they name one `repository_commit` and one dataset snapshot. |
| 11 | Fixture/team bridge | PASS | `scripts.run_calendar_recalibration --time-aware` with both manifests completed with `fixture_conditioned_reporting: true`; fixture groups non-empty (single 32,083 / double_plus 1,020 evaluation rows; 828 double-gameweek player scales); the fixture join raised no unknown-team error. |
| 12 | Historical GW1 residual feasibility analysis | PASS | Delivered as the completed blocker report [gw1_blocker_report_2021-2026.md](gw1_blocker_report_2021-2026.md); "infeasible" is an accepted outcome under this item. Closing #45 on it is a three-owner decision, not part of this acceptance. |
| 13 | BO-ready deterministic prediction builder | PASS | `DevelopmentFoldPredictionEvaluator` implements the seam; `bind_policy_evaluator` accepts it; the synthetic search is deterministic. The seam gap it recorded (`risk_aversion` could not be pinned) was closed on this side in PR #90 (`BayesianFactor` fixed factor); the gap tests are now tests of the pinned search. |
| 14 | Prediction factor mapping | PASS | `form_window` passes through `FormWindowMapping` unchanged; a nonzero `risk_aversion` is refused rather than ignored, and the contract refuses missing/unexpected factors. |
| 15 | Candidate evaluation cost/runtime | PASS (delivered after acceptance) | Measured in PR #95 ([candidate_runtime.md](candidate_runtime.md)): candidate 590.3 s / 147 folds (4.02 s per fold) against control 11.7 s — about fifty times the cost, ~7% run-to-run spread, machine and stopping rule named. Informational; gates nothing. |
| 16 | Quality gates | PASS | On `93a87d6`: `pytest` 1785 passed / 1 skipped; `ruff check` clean; `ruff format --check` 257 files formatted; `mypy --strict src` clean over 119 files. |
| 17 | Declaration and config fingerprints | PASS (computed) / PENDING (frozen) | `scripts.freeze_candidate_declaration` re-run here reproduces the committed JSON **byte for byte**: declaration `f72962a182e4d857448d860641c7ebc211a4f7101f3ed713362636fa2b3bce09`, benchmark configuration `b64a3ab9f06f1c1a207d66c8f1d59b0c3072f7fe8400cb598e378fca37e6f575`. Freezing requires all three owners; the optimization side's review is recorded, the architecture/CI side's is pending. |

## The finding: the candidate export is not byte-reproducible across machines

The control export reproduces exactly (four commits, two machines, one hash). The
candidate export does not: same commit, same dataset snapshot, same 147 folds and
101,447 rows, preflight 31/31, and a different `table_sha256`.

The content agrees to every reported decimal. Overall candidate bias `-0.0421`, MAE
delta `-0.0047`, SD delta `-0.1017` — the numbers PR #80 reports — reproduce here to
four decimals from the regenerated table. The time-aware recalibration study
re-run on the regenerated pair reproduces every coverage, width, and decomposition
figure in `time_aware_recalibration.md` to four decimals and reproduces the
configuration fingerprint (`0e01ee3c…`) exactly; only the measurement and study
fingerprints differ, because they are derived from the table bytes.

The cause is where the arithmetic differs from the control: `fit_learned_rate` solves a
ridge system with `numpy.linalg.solve`, and the LAPACK/BLAS behind it is not the same
library, or not the same instruction path, on two machines. The predictions are written
at up to sixteen significant digits, so a last-bit difference in a coefficient becomes a
different CSV. This is the delivering side's own concern from PR #80 — "a number that
moves with the numerical environment makes a gate threshold move with it" — showing up
in the export rather than the gate.

What this means for the procedure, stated rather than repaired here (the export is the
prediction side's module):

- A candidate `table_sha256` identifies **a** table, not **the** table for a commit.
  Two owners running the same commit will legitimately record different hashes. The
  pair check and the study fingerprint are therefore machine-scoped; the reproducible
  claim is "same commit, same content to the reported precision", which is what the
  runbook's step-3 review actually needs.
- Two clean ways to make the hash mean what it reads as: round `predicted_points` to
  a declared precision (1e-9 is far below any reported decimal) before hashing, or
  publish an equivalence tolerance next to the hash. Either belongs in
  `oos_residual_export_v1`'s successor, not in this acceptance.
- **The formal gate is not affected in its verdict**, but its record should name the
  machine: a benchmark score that depends on the last bit of a coefficient is possible
  in principle, and the honest record is one where a second executor can tell whether
  a difference is the environment or the candidate.

## What this record does not do

It does not freeze the fingerprints (three owners), does not run Stage B, does not read
the locked holdout, and does not modify any delivered file. Regenerated tables stay
local under `artifacts/residuals-verify/`; this document is the committed record.

## Follow-up: how the finding was resolved (PR #94, PR #95)

The prediction side measured the finding rather than choosing between the two remedies
offered above ([export_precision.md](export_precision.md)): perturbing the real
101,447-row table by a last-bit-sized relative amount (1e-16) moves **all 58,855**
non-zero unrounded values — two machines disagreeing was certain, not unlucky — while
nine written decimals move zero rows at 1e-15 and one row at 1e-14. `oos_residual_export`
now writes `predicted_points` at nine decimals with the precision declared in the
manifest, and the tolerance-beside-the-hash option was rejected on the right ground: a
checksum's job is integrity, and an approximate-equality checksum cannot detect a
corrupted file.

Two consequences this record's numbers inherit:

- **The control hash quoted in item 8 (`1ed41f94…`) is superseded once**, to
  `98b9dd20…`, because a pair whose halves are written at different precision is not a
  pair. What `1ed41f94…` proved — byte reproducibility across four commits and two
  machines — stands; the new hash is the one future runs must match. The candidate hash
  is now `d556938a…` on the delivering side and should reproduce here; that check is a
  routine re-run of item 9, not a new acceptance.
- **The residual identity is no longer exact** (recomputed from the rounded projection;
  measured 3.55e-15 across real rows, well inside the preflight's 1e-10).

PR #95 also carried the Stage A review's one observation into the gate report (rate-rung
counts lifted by prefix, absent rungs omitted rather than shown as zeros), so the formal
run's diagnostics will show the ladder comparison this record asked for.

