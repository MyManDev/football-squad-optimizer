# Issue #38 — The Uncertainty Layer's Decision on the Recalibration Evidence

[time_aware_recalibration.md](time_aware_recalibration.md) ends with: "Whether the
calibration is updated on this evidence is the uncertainty/scenario owner's decision, not
this document's." This is that decision, made against the issue's acceptance criteria and
against what the operational system actually wraps its intervals around.

## Where the acceptance criteria stand

| Criterion | Status | Where |
| --- | --- | --- |
| Conformal coverage re-measured on calendar-aware residuals; widths compared overall and by fixture count | **Met** | Held-out coverage 0.9019 / 0.9019 on singles at 7.2% narrower width; doubles 0.8304 vs 0.8039; replicated independently to four decimals in [issue43_handoff_acceptance.md](issue43_handoff_acceptance.md) |
| Player-adaptive scales refitted; shrinkage change for double-gameweek histories reported | **Met** | 828 players' scales, deltas predominantly negative |
| Scenario decomposition re-examined | **Met** | Common-gameweek SD halves (0.146 → 0.072); team-gameweek and idiosyncratic components shrink |
| Calendar-blind figures re-run or labelled | **Met** | Both regimes are labelled by manifest and measured on one matched population |
| Fixture-conditional behaviour reported, not pooled | **Met** | Every table is split by fixture group |

The evidence is complete. The question left is what to do with it.

## The decision

**The operational uncertainty and scenario calibration stays bound to the operational
control's residuals. #38 stays open until the #43 verdict is recorded, and closes with
it either way.** Reasoning:

1. **A calibration is conditional on the model it wraps.** The candidate's tighter
   intervals are tighter *because the candidate's projections are different*: the
   calendar effect moved from the residual into the point projection. Attaching the
   candidate-fitted scales, conformal multipliers, or scenario components to the
   control's projections would put intervals around a projection that still carries
   the calendar in its residual, and the first double gameweek would show it as
   undercoverage. The live risk layer already refuses a residual history whose model
   identity does not match the projection's, and that refusal is the same principle
   applied here.
2. **The candidate is not operational.** The formal gate has not run (Stage A is
   pending the third owner; see [issue43_stage_a_review.md](issue43_stage_a_review.md)).
   Until a verdict is recorded, the calendar-aware regime is a measured possibility, and
   its calibration is evidence about that possibility.
3. **If #43 promotes**, the calibration is re-fitted from the candidate's own OOS
   residual export under the existing leakage-safe procedure — the study above *is* the
   dry run of that step, so nothing needs to be invented. **If #43 does not promote**,
   the control's calibration is unchanged and correct as measured, and #38 closes with
   the evidence on record.

So this is not a refusal of the evidence; it is a statement of what the evidence is
evidence for.

## The model-independent finding, and what to do about it

Both regimes undercover double gameweeks (0.83 and 0.80 against nominal 0.90). The
candidate does not fix this; it makes it slightly worse, because narrower intervals on an
already-undercovered group undercover further. And the study names the cause: conformal
intervals are marginal and lean on exchangeability, and a double gameweek is not
exchangeable with a single one.

That is a fact about the **calibration**, not about either model, and it is this layer's
to fix. The calibration groups today are positions
(`squadopt/uncertainty/calibration.py` groups by `POSITIONS`); the fixture count is not a
grouping axis, so a double gameweek borrows the single-gameweek multiplier. Two things
follow:

- **Next measured step for this layer**: a fixture-group axis in the conformal stage —
  position × {single, double_plus} multipliers, with a pooled fallback where a group is
  too small (the double_plus evaluation group is 1,020 rows; the 30-observation floor
  already in `UncertaintyConfig` applies). Blank rows are zero by construction and need
  no interval. This is measurable today on the control's residual export with the
  fixture bridge the recalibration script already builds; it does not need the
  candidate, and it would give the live risk layer an honest lower tail on the double
  gameweeks that matter most to it. It is scoped as a follow-up rather than done here
  because it changes a frozen calibration contract and deserves its own declaration.
- **Until then, the live report should say so.** A double-gameweek lower tail from the
  current calibration is optimistic by roughly the coverage gap above; the live risk
  layer's diagnostics can carry that as a stated limit rather than a silent one.

## Follow-up recorded

The fixture-group axis was measured on the control's export on 2026-08-18
([fixture_group_conformal_note.md](fixture_group_conformal_note.md)): held-out
double-gameweek coverage rises from 0.849 to 0.901 against nominal 0.90, singles narrow
slightly and stay above nominal, no cell needed the pooled fallback. The
`projection_uncertainty_v2` declaration is the next step; the operational contract is
unchanged until it is made.

## What this decision does not do

It does not change any calibration artifact, control, or contract; it does not touch the
#43 gate; it does not read the locked holdout. It records where the uncertainty layer
stands so the next owner to act — the third Stage A reviewer, or whoever picks up the
fixture-group conformal work — starts from a stated position rather than an inferred one.
