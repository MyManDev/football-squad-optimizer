# Member gameweek live inputs

Refs #1008. Contract: `week_live_v1`. The schema is
`week_live_v1.schema.json`. This contract defines inputs and a display calculation;
it does not connect a reader, write a weekly stage or change the system squad card.

## Inputs and identities

The document carries a season, gameweek, UTC source time, captured fixtures and
per-element points. A fixture has its FPL fixture id, home and away club ids and
the captured `finished` boolean. An element has its season's FPL `element_id`,
signed integer points, non-negative integer minutes and `card_shown`, true for
either a yellow or a red card. No minute is manufactured from a card.

These are element and club ids from that season's FPL payloads, not persistent
player or club codes. The member block uses the same element ids. Never join a
pick directly to a device row's persistent code. Source A resolves position and
club by `element_id` from #981's per-capture table; source B includes `position`
and `club` on elements, resolved on the server. Both must supply a known position
and club for every pick before scoring.

`source_time` records acquisition of the input bytes, not page-open or refresh
time. A last-good response retains its original source time. The live and picks
blocks must refer to the same season and gameweek. Points are the current live
totals, not projections, BPS or recomputed bonus. Minutes aggregate the whole
gameweek, including every fixture in a double week.

The reusable `memberWeek` schema is at `#/$defs/memberWeek`. It carries `entry_id`,
gameweek, fifteen unique `pick_order` element ids, captain, vice, active chip and
the captured transfer cost. Positions 1 to 11 are the named starters; positions
12 to 15 are the captured bench order. Captain and vice are different named
starters. Transfer cost is `entry_history.event_transfers_cost` from those picks,
deducted once. Optional `entry_history_points` is the gross official week value
from the same picks, retained for the declared finished-week check.

Source A serves the trimmed document and supplies the member block from #980's
entry bundle. Source B supplies member blocks in `members`. Neither is selected
by this contract. Source A requires #979's served verdict, the owner's yes and
İbo's agreement on #980; otherwise source B applies as #1008 declares.

## Validation before calculation

The schema rejects unknown fields, chips, non-integer scores and minutes,
boolean numbers, malformed source times and duplicate pick ids. Consumers also
reject duplicate element, fixture or member identities; identical home and away
clubs; mismatched season/gameweek; a missing picked element; an unresolved club
or position; and captain/vice outside the starting eleven or equal to each other.
The fifteen positions must contain 2 GK, 5 DEF, 5 MID and 3 FWD. The named eleven
must contain one GK and meet the official formation bounds: DEF 3 to 5, MID 2
to 5 and FWD 1 to 3. The bench has the remaining goalkeeper and three outfield
players. JSON Schema establishes the wire shape; the scorer establishes these
cross-field and football identities.

## Official scoring and progress

The finished rule is `official_autosub_captain_v2`, implemented by
`score_frozen_squad_decision` and the chip arithmetic of `score_recorded_decision`.
Participation for substitutions means positive minutes or a card. Captain
fallback uses actual positive minutes, including when a zero-minute captain has
a card.

For a club, completion means every captured gameweek fixture involving that club
has `finished: true`. A known club with no gameweek fixtures is complete. An
unresolved club is an input error. Completion is decided per club, not from the
player's minutes or from a fixture's start time.

During an unfinished week:

1. Keep a named starter unless he did not take part and his club is complete.
2. Replace the absent starting goalkeeper only with the bench goalkeeper who
   has taken part. A pending bench goalkeeper does not block the outfield walk.
3. Walk outfield reserves in captured bench order. Skip a completed non-player.
   Stop at the first reserve who has not taken part and whose club is incomplete.
   For each participating reserve, choose the first eligible missing outfield
   starter whose replacement keeps the nominal formation legal, exactly as the
   Python scorer does. A still-pending starter is not eligible to go off.
4. Keep the captain's extra copy until his club is complete. If he then has zero
   minutes, give it to the vice only if the vice has positive minutes and belongs
   to the provisional counted eleven. If neither qualifies, add no extra copy.
   Negative armband points are still added with their sign.
5. Triple Captain adds one further copy of the same eligible armband points.
   Bench Boost counts all fifteen plus the eligible captain copy; it does not
   add substitution points a second time. Free Hit and Wildcard use normal-week
   scoring. An unknown chip is refused.
6. Subtract the captured transfer cost once to obtain the displayed net points.

Once every fixture is finished, these rules reduce exactly to the Python
reference. Formation counts follow the nominal eleven while choosing legal
substitutions; the final counted eleven omits definite non-participants. This
retains the Python behavior when too few reserves played to restore eleven.

## Display and persistence

The future card exposes net points, transfer cost, finished fixtures out of total
fixtures, bonus state, armband holder, substitutions already made and source time.
Bonus state is confirmed only in the finished state, following the existing
reader's `bonus_confirmed` rule. The numbers come from the live totals as provided; the
card never adds bonus again. An unfinished captain can remain the named holder
with zero points while fallback is pending; after completion, no eligible holder
is represented by null.

Read on page open or an explicit refresh only, without a timer. Source A's cache
is 60 seconds for the current unfinished week and until the next deadline for a
finished week. When no valid source answers, show no card. Member labels in both
languages carry the values and states without explanatory sentences.

This calculation never writes to the ledger, outcomes, scoreboard, records or
measurements. The release and the first finished-week equality check remain the
gates in #1008. The system squad's `/gw` card and `live_score_v1` stay as they are.

## Synthetic schema examples

`week_live_v1.examples.json` contains one in-progress document and one finished
document, with fifteen invented elements and a member block. They are offline
schema examples, not published data or scoring observations. The schema test
validates both documents, each member block separately and the trimmed source A
form without member blocks.
