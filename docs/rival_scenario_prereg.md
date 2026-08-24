# Pre-registration: the rival as a distribution, and the calibration gate a probability claim must pass

Written **2026-08-22, before any implementation exists**. The gate is fixed here so it
cannot drift toward the numbers once they arrive. This is the successor to
`rival_edge_prereg.md`, whose constant-edge term passed its own gate (#156): claims
deflated toward reality (h=3 claimed 0.97 → 0.87) but stayed **diagnostics, not
probabilities**, because a constant fixes the rival's location and leaves its dispersion
at zero. The site still ships price tags only, and this document defines the one gate
that can change that.

## Why

A rank claim compares two random variables — our squad's score and the rival's — but
today only one of them is random. The rival enters every scenario as (control projection
of its eleven) + (a constant edge). A rival with zero variance makes P(ahead) too sharp
in both directions: overconfident when the margin is small, and blind to the correlation
between our score and the rival's (shared players, shared gameweek shocks), which is
exactly what decides close weeks in a mini-league where squads overlap heavily
(`template_rival_strength.md` measured the crowd sharing most of its eleven with ours).

## Amendment, 2026-08-23, before any calibration run exists

The first draft of this section misdescribed the code: `_rival_scores`
(`scenarios/rank.py`) already scores the rival's eleven through the same scenario matrix
as ours — shared draws, shared players cancelling, covariance priced. Reading the code
before building is what caught it. What the model actually lacks is measured, not
guessed: the crowd's weekly edge over the projection is not the constant +7.19 the edge
term adds but a random variable with a **weekly standard deviation of 18.0 points**
(range −42..+62 over 2024-25's 37 folds) and **no meaningful week-to-week persistence**
(lag-1 autocorrelation 0.07). A three-week window therefore misses ~√3·18 ≈ 31 points of
rival-side spread — which is why h=3/5 claims stayed fiction (0.87 claimed, 0.00
realized) even after the location was fixed. The gate below is unchanged from the first
draft; only the mechanism and the population are corrected, and both corrections were
made before any calibration number existed.

## The change, in one sentence

The rival's per-scenario score gains a **per-week edge draw resampled from the measured
weekly edge series of the other development seasons** (leave-one-season-out, empirical
resampling — no distributional fit), independent across the weeks of a window, replacing
the zero-variance constant; the constant remains as the degenerate fallback and the
zero-change default.

Mechanically: `RankObjectiveConfig` gains `rival_edge_samples` (a tuple of measured
weekly edges; empty = constant-only, bit-for-bit today) and a deterministic seed; the
solver and `compare_fixed_decisions` add one resampled draw per scenario per week to the
rival's scenario scores. Nothing about how the rival's *players* are scored changes.

## Declared before measurement

- **Edge series**: `measure_template_rival` run per development season (2021-22..2024-25,
  37 folds each); season S's calibration draws only from the *other* seasons' series.
  The 2024-25 series artifact predates the holdout spend and its provenance shows
  2025-26 rows were loaded as history (not scored); recorded here for completeness —
  the holdout was spent on 2026-08-22 and is no longer at stake.
- **Population**: every fold of the four development seasons at each horizon (windows
  clipped at season end), claims produced by the **fixed-decision path**
  (`compare_fixed_decisions`) on the fold's held squad — cheap enough for ~140 windows
  per horizon, against the five per horizon the first windowed run could afford. The
  three-phase solver is exercised by the decision-stability clause, not by the
  calibration population.
- **Rival**: the ownership template rival (`template_rival_from_ownership`), unchanged.
- **Horizons**: 1, 3, 5 — the product's windows.
- **Instrument**: claimed P(ahead) per fold versus realized ahead-frequency, pooled and
  per season; the fold-level bootstrap for intervals, as in `windowed_rank_note.md`.

## The gate

1. **Shared-draw identity.** A player present in both squads contributes *identical*
   per-scenario points to both sides — proven by test on the matrix, not argued. His
   net effect on the differential must be exactly zero in every scenario.
2. **Zero-change fallback.** With the rival-distribution switch off, every existing
   output is bit-for-bit unchanged (scenario fingerprints, rank rows, plan selections).
3. **Calibration, this time.** Pooled over folds, at every horizon:
   `|claimed − realized| ≤ 0.10`, and the 90% bootstrap interval on the gap must
   contain zero. This is deliberately stricter than the edge prereg's
   "deflation-not-calibration" clause — that clause bought honesty about direction;
   this one buys the right to print a number.
4. **No horizon sacrificed.** The h=1 gap must not worsen by more than 0.02 against the
   constant-edge baseline while h=3/5 improve.
5. **Decision stability.** Mode selections on the plan menu (`plan_selection.MODES`)
   re-run under the distributional rival; the *ranking of modes by claimed safety* must
   agree with the constant-edge run — if making the rival honest reorders the product's
   own safety story, that is a finding to publish, not a knob to tune.

## What passing and failing mean

- **Passes**: windowed P(ahead) may appear in member-facing advice as a probability,
  with the calibration artifact linked beside it. The price-tag presentation stays; the
  probability joins it, never replaces it.
- **Fails**: the site keeps shipping price tags only, this document records the failure,
  and the next attempt needs a new pre-registration naming what changed. The claim
  stays a diagnostic — exactly as today.

Measurement only until the gate says otherwise; nothing here touches the live decision
path, and `prediction/` is not involved.
