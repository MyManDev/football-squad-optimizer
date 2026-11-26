# ADR 0026: One week-state rule for every web consumer

- **Status:** Proposed, awaiting the owner's explicit answer before implementation.
- **Date:** 2026-11-26.
- **Decider:** The owner.
- **Related:** [Member page boundaries](../member_page_boundaries.md), [ADR 0012](0012-fpl-forwarder.md).

## Context

The published plan stays on its captured gameweek after its deadline, through play,
completion and checking, until the next publication. Calendar and result views need
different weeks during that interval. Today those choices are made independently.
One policy should decide the phase and the week appropriate to each consumer.

The inspected base is `95230aac536164ff73f205bc44033c1a97d110cd`. In that base
[fixtures](../../../web/src/features/fixtures/weeks.ts) advance at the last kickoff,
[LIVE](../../../web/src/features/liveScore/liveWindow.ts) leaves at the last kickoff
plus 180 minutes, and the member fixture rail stays on the plan's week. The
[latest-result card](../../../web/src/features/league/pages/lastWeekResult.ts)
already selects the highest `finished` week, rather than always plan week minus
one. Preserve that selection while moving its policy into the shared module.

## Proposed decision

Add a pure `web/src/lib/weekState.ts` after approval. Its inputs are the published
tree gameweek, the events list with `finished` and `data_checked`, the fixture
calendar and an explicit clock. Its output names one of the six phases below,
the target weeks, plan closure and the next clock transition. Consumers select
from that output; they do not choose a week by applying their own clock or flags.

The clock is never earlier than the calendar capture, preserving `calendarClock`.
Missing inputs return a typed unavailable state with nullable targets, rather
than pretending that a missing week is blank or inventing a deadline. A known
published plan week remains available even when calendar targets are unavailable.

### Week names

- **P:** the published tree's gameweek. Only a new tree changes it.
- **N:** the calendar week whose lifecycle is followed. Select the latest
  elapsed-deadline week until it is checked and a newer publication names a
  future listed week; then select that published future week before its deadline.
  Before the first deadline, select the earliest future listed week.
- **Q:** the next listed calendar week after N, or no week at season end. Never
  substitute N + 1 for an absent calendar week.
- **F:** the latest elapsed-deadline event marked `finished`, or no result yet.
- **C:** the latest elapsed-deadline event marked both `finished` and
  `data_checked`, or no checked result yet. C can lag F by several weeks.

The table describes N's lifecycle, commonly with P = N. A new publication after
phase 6 starts phase 1 for its future week. If inconsistent inputs instead name
a newer tree P = Q while N is still being played, planning uses P and match views
continue to use N. Plan closure is always evaluated at P's own deadline. The
latest elapsed deadline always takes precedence over an earlier lifecycle.

### Six phases and exact boundaries

| Phase | Definition for N |
| --- | --- |
| 1. Before deadline | The effective clock is strictly before N's deadline. |
| 2. Deadline passed, before kickoff | The deadline has been reached and no dated fixture has reached kickoff. |
| 3. Matches being played | At least one dated fixture has reached kickoff and the week has remaining fixture time, including gaps between matches. |
| 4. All played, not finished | Each assigned fixture is marked finished or has reached kickoff plus 180 minutes, but N's event is not `finished`. |
| 5. Finished, not checked | N's event is `finished` and not `data_checked`. |
| 6. Checked, awaiting publication | N's event is both `finished` and `data_checked`; P can still be N. |

After the deadline, checked and finished event flags take precedence over fixture
time, in that order. Time alone never makes a finished or checked result. Phase 4
is the end of the existing match-following time limit, not a score-finality claim.
At an exact deadline, kickoff or 180-minute boundary, the later phase applies.
The next elapsed deadline selects the next N even if the tree has not advanced;
completion of the older N remains represented by F and C.

For a listed blank week with zero assigned fixtures, the deadline goes straight
to phase 4 unless event flags already select phase 5 or 6. In a double week,
every assigned fixture counts, including the later match. An unfinished fixture
with no dated kickoff prevents the time-only transition to phase 4. With none
started, phase 2 remains; after one has started, phase 3 remains. A revised
kickoff is read from the supplied calendar, rather than retaining an obsolete
time. Missing event rows can support phases 1 to 4, never phases 5 or 6.

### Consumer decision table

`F` and `C` below denote all eligible rows through that target, where a view is a
list or a cumulative total. A target only selects a week: a value still requires
a same-week document for the same member, league and season. Missing values keep
their existing empty or absent presentation. No cross-week value is relabelled.

| Page or part | 1. Before deadline | 2. Before kickoff | 3. Playing | 4. Played, not finished | 5. Finished, not checked | 6. Checked, awaiting publish | Why |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Member top bar week and deadline | P | P | P | P | P | P | It identifies the published decision, not the next calendar week. |
| Plan, tools and chip decisions | P, open if P's deadline is open | P, closed if P = N | P, closed if P = N | P, closed if P = N | P, closed if P = N | P, closed if P = N | A passed deadline cannot be reopened by a result flag or a calendar rollover. |
| Bank and free transfers | P while open | Absent if P closed | Absent if P closed | Absent if P closed | Absent if P closed | Absent if P closed | Preserve the top bar's current closed-week behavior; do not assign old resources to Q. |
| Fixtures page, default week | N | N | N | Q | Q | Q | Keep the last match visible while its window remains, then show the next listed week. |
| Member fixture rail, first column | P while open | N if P closed, otherwise P | N if P closed, otherwise P | Q if P closed, otherwise P | Q if P closed, otherwise P | Q if P closed, otherwise P | An open plan keeps its own horizon; a closed plan's rail follows the same calendar transition as fixtures. |
| Member current/live score card | Latest elapsed week, when held | N, awaiting first match | N | N, retain held score | N | N | The actual score belongs to the played week until its replacement is read, independent of P. |
| LIVE page | Wait for first kickoff of N | Wait for first kickoff of N | Follow N | Wait for first kickoff of Q | Wait for first kickoff of Q | Wait for first kickoff of Q | LIVE remains for following matches; result checking does not extend its time window. |
| Phone LIVE pill | Off | Off | N only during a member match window | Off | Off | Off | Preserve the member-club filter and existing bounded request policy. |
| League scoreboard rows | F | F | F | F | N, if its row exists | N, if its row exists | A finished result can be shown before checking, as it is today. |
| Latest-result card | F | F | F | F | N, if its member net exists | N, if its member net exists | Select the latest finished week even while P is still N. |
| League cumulative totals and race | C | C | C | C | C | N, if checked rows exist | Standings history uses checked results, not a clock-derived result. |
| Member history scored comparison and season totals | C | C | C | C | C | N, if a settled history row exists | Checking grants eligibility; it cannot synthesize unpublished suggestion scores. |

For the rail, only its calendar columns advance when P is closed. Players remain
those of the held squad, and closed-week transfer rows remain absent. The
fixtures page keeps its five-week range and the rail its three-week range.
Explicit user selections of an older fixture or history week remain selected.
Existing unsettled or unavailable history rows remain visible with their current
status and values; C controls scored comparisons and totals, not row removal.

The latest-result card may say "last week" only when F = P - 1. Otherwise it
uses F's explicit week label, preserving the current rule. Rank movement requires
that same scored week; suggestion points require that same settled history row.
The scoreboard's cumulative total continues to use C even when its newest row
is F. The tree's totals and ranks retain their own scored-week identity.

The member match window keeps its 135-minute ordinary window, extension to
180 minutes when the held live read names an unfinished match, and bounded slow
following for a stalled match. These decide polling and the pill inside phase 3,
not a second choice of gameweek. Between matches LIVE stays on N while the pill
can be off. Match-level activity, goals, substitutions and replay remain
match-level policies, outside the choice of week.

### Alternatives and review choice

1. Advance every view with P: the fixture calendar and live results wait for a
   publication that deliberately happens later.
2. Advance every view at the deadline or the last kickoff: a plan or unchecked
   result would acquire another week's identity; the last match can disappear
   while still being followed.
3. Use one phase policy with separate, named week targets: proposed above.

The owner is asked to approve or amend option 3, including these visible changes:
fixtures retain N past the last kickoff until phase 4, and a closed member rail
advances to Q at that same boundary. LIVE also ends immediately if authoritative
completion selects phase 4, 5 or 6 before its current 180-minute limit; its held
result remains on the member card. Otherwise its existing upper limit remains.
The latest-result, closed bank and free-transfer rules above are existing
behavior, not additional removals. No other currently visible value is removed.
This draft is the review stop. No module or consumer implementation starts
without the owner's explicit answer.

## Delivery and acceptance after approval

First add the pure module and transition tests. Cover deadline minus and plus
one second, exact deadline, first kickoff, last kickoff, last kickoff plus 180
minutes minus and plus one second and the exact limit, each flag change, gaps
between matches, a blank week, a double week, undated/postponed fixtures, missing
inputs, an ahead/behind tree, the next deadline and the final week.

Then use one PR per group: fixtures; member page and rail; LIVE and pill; league
scoreboard and race; history. Each group tests that its target changes only at a
module transition or an explicit user selection/publication. Existing values
are preserved under their proper week, and new Turkish and English UI copy, if
needed, belongs in the existing message catalog.

Finish by listing every remaining week selector using a clock, deadline or
event flag; none may choose a week outside the module. Match activity and timer
scheduling are not week selectors. Run the prescribed web checks and browser
suite after a fresh build. A publishing, backend or contract change is outside
this proposal; if required, stop and report that boundary before editing it.
