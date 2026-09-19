# The window solved with a named chip forced: protocol

Status: pre-registered on 2026-09-19. Nothing under this protocol has been run. It changes no
plan, price or live control, nothing here is member-facing, and no code under `planning/` is
touched by this document. Tracking issue: #659; it is the amendment item of
`docs/chip_forecast_prereg.md`.

## The question, and the one it is not

The weekly rule decides whether a chip is played this gameweek and which gameweek it currently
points at. That is settled and measured: a planner that can reach a chip inside a finite window
spends it, because the window counts nothing for holding it back, which is why every member solve
is handed an empty chip availability under the stated limit `NO_CHIP_LIMIT`; and
`transfer_discipline_value_rolling` measured the rolling planner holding chips at **1968** against
**2016** for the calendar rule and **2018** for the weekly control. **This protocol does not
reopen any of that.** The window never decides whether a chip is spent.

What is open is narrower. Once the weekly rule has named a gameweek for a chip the member holds,
the member still has to decide what to do **this week**. The question is whether knowing the named
week changes that: whether a three or five week plan solved with the chip pinned to the named week
recommends different transfers now than the same window solved with no chip at all.

- If it recommends the same first week, the card can name the week and stop, and the member's plan
  needs no second version.
- If it recommends a different first week, then a member who follows the chip-less plan is
  preparing badly for a chip the same system told them to hold, and the card owes them the
  prepared plan.

## The two arms

Per member, per window length (3 and 5), per chip the member still holds whose named gameweek
falls inside that window:

- **`no_chip`**: the window exactly as the product solves it today, empty `ChipAvailability`.
- **`forced`**: the same window, same capture, same projection, same budget, with
  `ChipAvailability(available={chip: {week}}, forced={week: chip})` for the named week, where the
  named week is the one the weekly rule of `docs/chip_forecast_prereg.md` points at.

A member with no chip named inside the window is not read. Nothing else differs between the arms:
same squad, same transfer configuration, same free transfers, same prices.

**Which rule named the week is part of the reading, not background.** `chip_forecast_rule` settled
it on 2026-09-19: the decaying threshold, with the bench boost reservation dropped. The record
states that in its first lines, by name and with the record it comes from, so that if the rule is
ever replaced this reading stays identified as a reading of the weeks **that** rule named, and
nobody has to reconstruct which one it was from the dates. A record written under a different rule
is a different record and says so in the same place.

## What will be read

1. **The first week, which is the only week a member acts on.** Whether the two arms' first
   gameweek differs at all, and how: players transferred in and out, the captain, the starting
   eleven, and whether a hit is taken. Counted over members and reported per chip and per window
   length. This is the reading; everything else is context for it.
2. **How far away the named week is**, beside every comparison: the named gameweek minus the
   decision gameweek, from 1 (the next gameweek) to the window's length. Without it a reader
   cannot tell two different reasons for "no difference" apart: a chip named for the next
   gameweek that still changes nothing this week is a finding, and a chip named for the last week
   of a five week window that changes nothing this week is close to arithmetic. Every count in
   reading 1 is reported by this distance as well as in total. On the published calendar as it
   stands there is no double and no blank gameweek ahead, so the far case is expected to be the
   common one, and a total that hides it would read as if the question had been asked and
   answered.
3. **The plan's value**, both arms, and their difference. Stated as what our own projection says
   under the same numbers in both arms, never as points the season will pay. A forced free chip
   can only raise the value inside the model, so the direction of this difference says nothing;
   its size beside the first-week difference is what is informative.
4. **The proof status of every solve**, at the window linearization level that
   `member_window_proofs` established. That record is the reason this reading cannot be taken at
   face value without it: at the solver default no window plan of that capture was proved, and at
   the window level the three week plans proved 15 of 15 while the five week plans proved 12 of 15
   with open gaps up to 10.37 points. **A value difference between two arms is reported as
   attributable only when both arms are proved.** Otherwise it is printed with the open gap beside
   it and is not counted in any summary, because a difference smaller than the gap can be solver
   slack rather than the chip.
5. The deterministic work and the wall seconds of every solve, so the cost of offering the member
   a second plan is on record before anyone proposes putting it on the page.

## The captures

The live captures of this season, newest first, starting with the newest capture on disk when the
run happens, and never a capture from inside a freeze window. Members are the league's, from the
capture, with their own squads only, and no member's advice is computed from another member's
squad. The record names the capture id and the handoff fingerprint it read. No projection number
moves, and no solver budget is raised to make a solve prove: the budget is the one the product
uses, and an unproved solve is recorded as unproved.

## What will not be claimed

- Nothing about which gameweek is the right one for a chip. That is the weekly rule's, under its
  own protocol.
- No realized points. There are none: this reads plans for gameweeks that have not been played.
  Every value here is a projection quantity and the record says so in its first line.
- No wording of chance anywhere, and nothing member-facing until a card exists and is reviewed.
- No claim that a differing first week is a better first week. It is a different one, under a
  chip the member has been told to hold.

## What follows

- If the first week is the same for nearly every member and chip, the record says so and the card
  names the week only. The expectation written before the run: the further the named week sits
  from the window's first gameweek, the less a forced chip should move this week's transfers, so
  the reading is at its most interesting when the named week is the next one or the one after.
  Reading 2 is what makes that expectation checkable rather than a thing said afterwards.
- If the first week differs, the prepared plan becomes a product question for the owner, and the
  cost measured in reading 5 is what it would cost to compute.

## The record

`docs/forced_chip_window.json` with its markdown twin and a row in `measurements_index.md`,
written by its runner, which refuses to overwrite its record, refuses to run inside a freeze
window, and names every capture it read. The comparison's arithmetic lives beside the other window
readings with unit tests on hand-built plans.
