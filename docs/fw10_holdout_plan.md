# form_window=10 Locked-Holdout Evaluation Plan

## Why this document exists

Real development-fold evidence now points one way for the deterministic policy:

- the exhaustive grid put `form_window=10, bench_weight=0.0` first (56.5034 mean
  realized squad points; the fw10 column holds ranks 1–7 outright);
- the recalibration dry-run showed the fw10 regime is also a tighter predictor at
  unchanged held-out conformal coverage.

The locked holdout (2025-26) is single-shot: it may be opened once for this decision,
and never re-queried after the result is seen. This plan freezes what that single shot
will be **before** anyone runs it, so the evaluation cannot drift toward the answer.

## The frozen decision

```text
challenger: form_window=10, bench_weight=0.0  (fw10-bw0)
control:    form_window=5,  bench_weight=0.1  (fw05-bw0p1, operational control)
mechanism:  scripts.run_frozen_holdout with the committed frozen_candidate.json
design:     screening_doe_v1 full factorial (4 windows x 3 bench weights)
objective:  single_gameweek_realized_squad_points_v1 (unchanged)
gates:      PromotionPolicy defaults — mean improvement >= 0.5 points/GW and
            90% season-aware moving-block bootstrap lower bound >= 0
```

The frozen candidate is produced by the committed development screening run
(`docs/fw10_screening.json` / `docs/fw10_frozen_candidate.json`), whose
`screening_fingerprint` and `configuration_fingerprint` bind the holdout run to
exactly this development decision. `run_frozen_holdout` refuses a configuration whose
fingerprint differs from the frozen one.

## Preconditions before the single execution

1. Three-owner agreement that the holdout is being spent on this decision — one
   comment per owner on the tracking issue.
2. Clean tree at a recorded commit containing the frozen candidate artifact.
3. The command, environment, and outputs archived together:

```powershell
.venv\Scripts\python -m scripts.run_frozen_holdout
```

4. No prior read of 2025-26 outcomes for this decision. (Known caveat, recorded
   rather than hidden: 2025-26 was scored by earlier sprint benchmarks of other
   layers, so it is not a pristine test set for the repository as a whole; it is
   still unspent for *this* policy decision, and the earlier exposure is listed in
   the holdout report's limitations.)

## What each outcome means

- **Promoted:** the operational control's `form_window` changes to 10 through the
  normal config-change process; live recommendation inherits it from the control
  definition. Uncertainty/scenario calibrations are re-derived under the new control
  (the dry-run already shows the expected direction).
- **Not promoted:** the control stays `form_window=5`; the result is recorded and
  the fw10 hypothesis is closed unless materially new development evidence appears.
  No re-runs, no threshold adjustments, no "one more look".

## What this plan does not authorize

Running the holdout. That execution is a separate, deliberate act by the owners after
precondition 1 is met. Nothing in the development artifacts committed alongside this
plan reads 2025-26.
