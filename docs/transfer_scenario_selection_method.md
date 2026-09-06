# Transfer candidates on shared component scenarios: method and validation plan

Status: method record and validation plan for `squadopt.scenarios.transfer_decisions`,
written before any measurement with it. It authorizes no member-facing change, no mode
renaming and no claim that the public mode names have a proven meaning.

## What it does

The member advice path plans transfers from a held squad under bank, free-transfer, hit and
chip rules; the deterministic plan the live path publishes is the control. The planner can
also produce alternative rule-compliant plans from the same start state (today: the transfer
menu, which re-solves with the previous first-week squads excluded). This module takes those
candidates as fixed decisions, scores every one of them on **one** shared
`ComponentScenarioDraw` with the official scorer (`official_autosub_captain_v2`, bench order and
vice-captain completed once by `optimizer_projection_order_v1`), subtracts each candidate's
transfer hit **once** from every scenario score, applies the frozen Phase E utility
(integer mean/CVaR, ρ = 0.25, α = 0.10, N = 1000) and keeps the frozen selection rule
(highest integer utility, ties to the lower rank, the control wins a tie).

It is transport-neutral: inputs are the planner's own week result (adapted by
`transfer_candidate_from_plan`), a `TransferStartState`, the draw and an explicit calibration
pin; the output is a `TransferScenarioSelection` with the selected decision, the retained
control, the status, the reason, the start-state, draw and sampler identities and a
per-candidate diagnostic table. Nothing here re-optimizes, reads an outcome or invents a pin.

## What it preserves and refuses

- The start state: every candidate must begin from the same held squad, bank and free
  transfers, and its post-transfer squad must equal the held squad minus its transfers out
  plus its transfers in. Anything else is an error, not a silent exclusion.
- The transfer rules: paid transfers are the transfers beyond the free ones, zero under a
  wildcard or free hit, and the hit must equal paid transfers times the planner's hit cost.
  The planner's objective (which already contains the hit) is never used to rank.
- Chips: a wildcard or free hit changes only the week's transfer accounting and is scored
  normally. A bench boost or triple captain changes the scoring arithmetic the official
  component scorer does not implement; such a candidate is excluded with a named reason, and
  such a control disables selection (`FALLBACK_UNSUPPORTED_CHIP`). No chip arithmetic is
  re-implemented here.
- The calibration pin: the draw's `(model_version, declared sampler)` must be on the pin the
  caller supplies, with the frozen seed-0 configuration; otherwise
  `FALLBACK_PHASE_D_NOT_CALIBRATED`. The production pin is empty, so today every call falls
  back to the control and records why.
- Coverage: a candidate with a squad player absent from the draw is not scored; an uncovered
  control or fewer than two scorable candidates gives `FALLBACK_SCENARIO_COVERAGE`.

## What a full-pool E2/E3 result does not establish here

Phase E generates complete squads from the full pool; its E2/E3 evidence concerns that
decision. A member transfer decision is constrained by holdings, hits and chips, its
candidates come from a different generator (the planner menu), and its outcome is a net score
after hits. A full-pool success is therefore not validation of this path, and this path makes
no claim about the public modes.

## Validation plan (written before results)

Historical folds cannot validate this path directly: the development export carries no
member holdings, so no historical start state exists. Validation is prospective:

1. **Shadow recording, not publication.** From the first eligible live gameweek, the advice
   path records, for each member, the control plan, the menu candidates, the selection
   result and the draw identity in ledger diagnostics. The published recommendation stays
   the control until the gates below pass and are reviewed.
2. **Outcome pairing.** After settlement, the realized official points of the selected plan
   and of the control are scored with the same realized scorer, both net of their own hit.
   D_w = selected − control per member-gameweek; a fallback week contributes zero and is
   kept.
3. **Gates, fixed now.** Over at least ten settled gameweeks:
   - harm excluded: the 90% season-aware moving-block interval of mean(D_w), with the same
     bootstrap policy Phase E uses, has a lower bound above −1.0 points per gameweek;
   - reliability: a named status on every member-gameweek and no raised errors;
   - usefulness: the selected decision differs from the control on at least 20% of
     member-gameweeks;
   - the recorded hit equals paid transfers times the season's hit cost on every record.
4. **Before any of it can act.** A calibrated Phase D pin for the sampler in use (the binding
   verdict is `failed`; the conditional sampler has a development pass only), and a reviewed
   note that names the sampler, the pin and the gate results.

No threshold above is tuned on results; a failed gate is recorded as a failed gate.
