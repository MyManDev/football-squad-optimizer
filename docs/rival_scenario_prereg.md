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

## The change, in one sentence

The rival's eleven is scored **through the same scenario draws as our squad** — common
and club components shared, idiosyncratic components drawn per player — plus the measured
location edge, so that P(ahead) prices both the rival's variance and the covariance a
shared player cancels.

Mechanically: `scenarios/rank.py` and `scenarios/rivals.py` stop receiving a fixed rival
row and start receiving the rival's per-scenario scores built from the *same*
`ScenarioSet` (and `ScenarioPathSet` for windows) that prices our candidates. The
constant `rival_edge_points` stays as the location term with its measured value; what
this work adds is the second moment and the cross-covariance, not a new mean.

## Declared before measurement

- **Population**: the same 147 development folds as `measure_windowed_rank`, seasons
  2021-22..2024-25, the 2025-26 archive refused by configuration (its holdout status at
  run time is recorded in the artifact either way).
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
