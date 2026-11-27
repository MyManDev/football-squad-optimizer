# Diagnostic: is the banked value reading inside the path noise?

Declared 27 Nov 2026 after the [pre-registered record](component_banked_transfer_value.md) was
written and read, before any number of this diagnostic was seen. It is post hoc. It does not
change the record's reading (`move` at 0.5); it says how much weight that reading can carry.

## Why

The record's primary cell reads `move`: a held free transfer worth 0.5 beats 0 by +2.60 a
week [+1.21, +4.07], season nets +0, +152, +89, +141. Two facts in the same record question
it:

- At 0.5 the planner keeps a free transfer it would have spent only 1 to 4 times a season.
  The chains part at gameweek 3 or 4 and never meet again, so each season's difference is
  the difference between two paths that split early, not the sum of the weeks where the
  threshold acted.
- The same threshold under each season's own bank cap, which differs from the primary only
  in weeks where five transfers could be held, gives 2022-23 at -48 instead of +152.

The weekly block bootstrap treats the 147 paired weeks as the data. If an early split moves a
season by as much as the threshold does, the interval is too narrow and the reading rests on
three path draws.

## What is walked

The primary cell (component base, bank cap 5 in every season), the whole grid of banked values,
the same code and seasons, with one change that should not matter: the solver's deterministic
budget a decision is **6** and **10** instead of 8. A budget changes which of several
near-equal plans the solver returns, and nothing else. Eight processes, artifacts under
`artifacts/component_banked_transfer_value/budget6/` and `budget10/`.

## What is read

1. **The path noise floor.** For each season, the season net of the policy's 0 at budget 6
   and at budget 10 minus its net at budget 8: how far a neutral change moves a season.
2. **The reading at each budget.** 0.5 against 0 at budget 6 and at budget 10, with the
   record's gate.
3. **Every level's gain against 0 across the three budgets**, to see whether any level keeps
   its sign.

How to read it, fixed now:
- If the budget changes move season nets by less than a third of 0.5's season gains, and 0.5
  passes the gate at both other budgets, the record's `move` stands as evidence.
- If a neutral change moves season nets by as much as 0.5's gains, or 0.5 fails the gate at
  either other budget, the record's `move` is read as path noise. The proposal to the owner
  is then to keep 0, and to measure a threshold only on a population of independent decisions
  (fresh squads a week), not on season chains.
- Anything between is reported as it is.

## The owner's level, 1.2

Added 27 Nov 2026, before any number of this diagnostic was seen: the owner named 1.2 as a
plausible value. It is walked as one more arm of the primary cell at budgets 6,
8 and 10 (twelve chains, `artifacts/component_banked_transfer_value/owner_level/`) and read
against 0 at the same budget with the record's gate, and against the path noise floor above.
It is a level named after the record was read, so a pass is reported as such and is not a
pre-registered reading.
