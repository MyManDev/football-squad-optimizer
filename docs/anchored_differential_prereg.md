# Pre-registration: the anchored differential — the successor rival_calibration's failure names

Written **2026-08-23, before any implementation exists**, the same day
`rival_calibration.md` failed its gate. That failure forced a diagnosis this document
turns into a mechanism; per the failed prereg's own rule, the new attempt gets a new
pre-registration, and this gate cannot move once the numbers arrive.

## What the failure proved

With the candidate fixed to the fold's risk-neutral squad, reality's differential
against the crowd **is** the measured edge distribution — the edge series is literally
`template_realized − risk_neutral_realized` per fold. The scenario side's contribution
to that pair's differential (a positive projection gap plus sampling noise) corresponds
to nothing that happens: claims sat at 0.76–0.90 against a realized ahead-share of
0.29–0.35 at every horizon, gaps +0.42/+0.55/+0.61 with intervals nowhere near zero.
No rival-side dispersion can cancel a location fiction on our own side.

## The mechanism

Decompose the claim's differential through the risk-neutral anchor:

```
candidate − crowd = (candidate − risk_neutral)   scored under the scenario draws
                  + (risk_neutral − crowd)       resampled from the measured edge series
```

The first term is honest scenario territory: both squads are priced by the same
projections, share most players, and their gap is small and centred near zero by
construction. The second term is measured reality, resampled leave-one-season-out
exactly as in `rival_calibration` (one draw per week of the window, iid across weeks —
persistence measured at ~0 in all four seasons). The fiction the failed run exposed —
the scenario-implied gap between our chosen squad and the crowd — never enters.

## Declared before measurement

- **Population**: the same folds as `rival_calibration` (four development seasons,
  horizons 1/3/5, opening folds skipped where the generator lacks eight historical
  folds; ~130–140 cells per horizon).
- **Candidates per fold**, chosen to span the shared-player spectrum the mechanism must
  price correctly, each a single deterministic CP-SAT solve:
  1. the risk-neutral squad itself (the degenerate pair);
  2. a **contrarian** squad — highest projection with the crowd's eleven excluded
     (maximum differential exposure);
  3. a **shadow** squad — highest projection with at least eight of the crowd's eleven
     forced in (minimum differential exposure).
- **Edge series**: unchanged from `rival_calibration` (`template_rival_strength*`,
  leave-one-season-out).
- **Instrument**: claimed P(ahead) versus realized ahead-frequency, pooled per horizon
  and per candidate family; fold-level bootstrap for intervals.

## The gate

1. **Degenerate identity, proven not argued.** For candidate (1) the scenario term must
   vanish by construction; the claim must equal the share of negative resampled window
   edges to within ±0.02. This pins the decomposition's arithmetic.
2. **Calibration.** Pooled per horizon *and within each candidate family*:
   `|claimed − realized| ≤ 0.10` with the 90% bootstrap interval on the gap containing
   zero. Families are gated separately because an average over opposite biases passing
   while both families fail would be exactly the kind of number this repository refuses.
3. **Ordering sanity.** The shadow family's claimed probabilities must sit closer to
   0.5-anchored-at-the-edge-share than the contrarian family's at every horizon —
   shared players must reduce, never increase, claimed certainty.
4. **Zero-change fallback.** The anchored path is a new claim construction, not a
   modification: every existing output of the direct path is bit-for-bit unchanged, and
   the anchored claim is opt-in.

## What passing and failing mean

- **Passes**: the anchored claim becomes the one construction allowed to print a
  windowed probability in member-facing advice, beside the price tags, with this
  artifact linked. The mode-ordering clause of the previous prereg is then re-run under
  the anchored construction before anything ships.
- **Fails**: price tags remain the only shipped claim, the failure is recorded here,
  and the next attempt — if any — starts from a new pre-registration naming what
  changed. Two failed constructions in a row would itself be evidence worth publishing:
  that windowed crowd-relative probabilities may not be honestly claimable from this
  scenario model at all.

Measurement only until the gate says otherwise; `prediction/` untouched; the locked
2025-26 holdout refused throughout.
