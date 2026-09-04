# Pre-registration: the rival-side edge term

Written **2026-08-20, before the change is implemented or any re-run exists**. The gate is
fixed here so it cannot be adjusted after the numbers arrive.

## Why

`windowed_rank_note.md` measured the failure: scenarios centre every player on the
control's projection, and the crowd's eleven scores **+7.19 points a week above** that
projection (`template_rival_strength.md`, 90% interval [+2.35, +11.97]). Inside the
scenarios the crowd is under-priced, so P(ahead of the crowd) inflates — claimed 0.97–0.99
against realized 0.00 at horizons three and five. A rival-aware probability is only as
honest as the rival's representation inside the scenarios.

## The change

One parameter with one meaning, default zero, at the three places a rival is scored:

- `RankObjectiveConfig.rival_edge_points` — added to the rival's scaled scenario scores
  inside the solver, so `ahead`, the claim, and the budget comparison all see it;
- `compare_fixed_decisions(..., rival_edge_points=...)` — added to the rival's float
  scenario scores;
- `plan_selection.rival_window_scores(..., rival_edge_points_per_week=...)` — added per
  week of the window.

The edge is a **single constant**, not a per-player model: the first estimate is the
measured +7.19 a week, and modelling *which* players carry the crowd's edge is later work
(Phase 5 territory). The value used is recorded in every diagnostics block and artifact;
it cannot be applied silently.

## The gate

1. **Zero-edge identity.** With the default `0.0`, every existing output is bit-for-bit
   unchanged — scenario fingerprints, rank rehearsal rows, plan selections. Proven by
   test, not asserted.
2. **Visibility.** The edge value appears in the diagnostics of every result it touched.
3. **Deflation, not calibration.** Re-running `measure_windowed_rank` with the edge at
   +7.19 must move the claimed probabilities **toward** the realized outcomes at horizons
   three and five (the inflation direction must break), and must not widen the
   claimed-versus-realized gap at horizon one. Exact agreement is *not* required — five
   windows cannot establish calibration, and pretending otherwise would be a new
   dishonesty. Calibration over a season of windows is follow-up work.

If clause 3 fails — the claims do not move toward reality — the recorded conclusion is
that a constant edge is the wrong shape, the parameter stays at its default everywhere,
and the negative is recorded. The bar is not moved after the fact.

## What is *hoped* but not gated

With the edge applied, the competitive modes (Garantici / Agresif / Aşırı Agresif) may
finally separate on the plan menu, where yesterday every chip plan sat at P≈1.00 against
an under-priced crowd. That is the interesting outcome, and it is deliberately not a gate
clause: mode separation on one window is an observation, not evidence.
