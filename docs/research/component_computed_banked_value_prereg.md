# Pre-registration: a held free transfer's value computed each week

Declared 27 Nov 2026, after the [fixed-level record](component_banked_transfer_value.md) and its
[path diagnostic](component_banked_transfer_value_path_diagnostic.md) were read, and before any
chain of this arm was walked. It reuses that record's chains for every fixed level; it adds one
arm. Nothing in this document (the arm, the rule that computes it, the comparisons, the gate,
the readings) changes after the first chain of the arm is walked.

## The question

The record priced a held free transfer at one constant for the whole season. Its worth is not
constant: it is zero in the last decision of a season, zero when the bank is at its cap, and it
grows when a double gameweek is next or when two moves together would buy what one cannot. The
question is whether a value the planner computes each week from its own forecast, instead of a
constant, plays better than the policy's 0 and than the constants 0.5 and 1.2.

## The arm

The primary cell of the record and nothing else: the component forecast, the 2026-27 rule (bank
cap 5 in every season), the member planning policy, lookahead 1, no chips, hit cost 8, charge 4.
The four seasons 2021-22 to 2024-25, 147 decisions, the same handoff and solver budget (8).

At each decision gameweek `t` the chain holds squad `S`, bank `B` and `f` free transfers. The
banked value of that decision is

    v_t = max(0, P(S, B, k_hold) - P(S, B, k_spend))

- `k_spend = min(cap, f)` is the number of free transfers next week if one is used now;
  `k_hold = min(cap, f + 1)` if none is. At the cap they are equal and `v_t = 0`.
- `P(S, B, k)` is the objective of the member policy's one-week plan for gameweek `t + 1` from
  squad `S` and bank `B` with `k` free transfers, banked value 0.
- The forecast of gameweek `t + 1` is gameweek `t`'s component forecast per fixture: a
  player's expected points at `t` divided by the player's club fixtures at `t`, times the club's fixtures at
  `t + 1`. A club blank at `t` carries the player's expected points at `t` unscaled (it is near
  zero); a club blank at `t + 1` is zero. The fixture calendar is the archive's, as every chain
  already reads it.
- In the last decision gameweek of a season, `v_t = 0`.

`v_t` then enters the decision exactly as a constant level does: the objective adds
`v_t × free transfers carried`. The squad `S` is the one held before the decision, not the
one after it; that is the rule's approximation and it is declared, not repaired.

Label: `component_rules_2026_27_bankcomputed`. Each decision costs two more one-week solves.

## Comparisons and gate

Paired over the 147 decisions with the record's moving-block bootstrap (block 4, 2000
resamples), and the record's gate: a mean gain of at least **1.5 points a gameweek**, a 90%
interval above zero, at most one losing season.

1. **Primary:** computed against 0 (the policy).
2. **Secondary:** computed against 0.5 (the record's passing level) and against 1.2 (the owner's
   named level). These are read by their interval only: better when the interval is above zero,
   worse when below, otherwise not separable.

## Readings, fixed now

- **`move`**: the primary passes the gate. If the computed value is also not worse than 0.5,
  the proposal to the owner is the computed value in place of any constant.
- **`direction`**: the primary's interval is above zero but the mean is under 1.5, or one
  condition of the gate fails with the others met. Reported as evidence for the owner, no
  proposal.
- **`unsupported`**: anything else. The constants stay as the record reads them.

## Described, not gated

Per season: the mean and the distribution of `v_t`, the share of decisions where `v_t` is 0,
the free transfers used, paid, lost at the cap and held on average (as the record counts them),
and the decisions where the computed arm holds a transfer that 0 spends.

## What does not change

No default and no product file. The rule lives in the experiment module as a chain that
overrides only the week's transfer configuration.
