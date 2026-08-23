# Pre-registration: the overlap-scaled edge — the third construction, named by the second's failure

Written **2026-08-23, before any implementation exists**, the same day
`anchored_calibration.md` failed its per-family gate. The trajectory so far, on the same
population: the direct construction missed by +0.42..+0.61 everywhere; the anchored
construction calibrated the risk-neutral family (gaps −0.013/−0.021/−0.047) and the
contrarian family (−0.003/−0.017/−0.010) and under-claimed only the shadow family, by
0.09–0.15, in one direction, at every horizon. This document turns that localized
failure into its mechanism, and the gate below cannot move once numbers exist.

## What the failure proved

The crowd's measured edge is carried by its **players**, not by the squad as a unit. A
candidate holding eight of the crowd's eleven inherits, in reality, most of the edge the
anchored decomposition assigns wholly to the anchor-versus-crowd term — so the more a
candidate overlaps the crowd, the more the resampled edge over-penalises it, which is
exactly the shadow family's one-directional under-claim. The two families with little or
no overlap were calibrated, which is why the mechanism below touches only the edge's
weight and nothing else.

## The mechanism — corrected before any code exists, 2026-08-23 (same day)

The first draft's verbatim formula block was internally inconsistent: its threshold
collapsed to zero for the degenerate pair, contradicting the draft's own clause 1. Caught
by re-deriving before implementing; corrected here while no code and no number exist. The
gate below is untouched.

One factor on the resampled edge draw, everything else unchanged from the anchored
construction:

```
claim = P( (candidate − anchor)_scenario  >  edge_draw × (1 − candidate_overlap) )
```

Why this form is forced by the two calibrated families rather than chosen: the edge
series is measured as crowd-minus-anchor realized points, so a candidate with zero
overlap (the contrarian family, calibrated at −0.003..−0.017) must face the full draw —
factor one, exactly the anchored construction it was calibrated under. The degenerate
pair keeps clause 1 *structurally*: the scenario term is identically zero and a positive
scaling never changes the sign of a draw, so the claim remains the share of negative
window edges no matter the anchor's own overlap. The shadow family (overlap ≈ 0.7–0.8)
faces a quarter of the edge, which is the failure's measured direction and size.

## Declared before measurement

- **Population, candidates, edge series, seeds**: identical to `anchored_calibration`
  (four development seasons, three families, leave-one-season-out pools, the same cell
  seeds), so the two artifacts are cell-for-cell comparable.
- **Overlap definition**: captain-weighted starter share against the crowd's eleven as
  fielded (shared starter 1, shared captain 2, denominator 12). Declared here once; not
  a knob.

## The gate

1. **Degenerate identity, exact.** Unchanged, and now structural: the scaling term is
   identically zero for the anchor.
2. **Calibration per horizon and per family**: |claimed − realized| ≤ 0.10 with the 90%
   bootstrap interval on the gap containing zero — all nine cells this time, including
   shadow.
3. **No family sacrificed.** The two previously-calibrated families must not leave
   tolerance: their gaps may not worsen by more than 0.03 against `anchored_calibration`
   cell-for-cell.
4. **Opt-in, bit-for-bit fallback**: scaling off reproduces the anchored construction
   exactly.

## What passing and failing mean

Passing: the overlap-scaled anchored claim becomes the single construction eligible to
print a windowed probability, subject to the previously-declared mode-ordering re-run
before anything ships. Failing: price tags remain the only claim, and — per the standing
rule stated in the first prereg of this line — a third failed construction is itself a
publishable finding: that windowed crowd-relative probabilities are not honestly
claimable from this scenario model, and the product line stops chasing them until the
scenario model itself changes.
