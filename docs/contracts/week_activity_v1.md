# Live player activity

Refs #1008. `GET /api/v1/fpl/live/{gw}?view=activity` returns
`week_activity_v1`: the unchanged `week_live_v1` document in `week`, plus
`activity`. The original route without a query still returns `week_live_v1`.
Both views use the same two FPL inputs and separate fresh and last-good cache
keys. Neither writes a result to the ledger. A page reads them on its own only
while one of the member's players' matches is being played (`week_live_v1.md`);
a read that adds goals, assists or cards against the reads before it plays the
GOL moment once (`web/src/features/liveScore/liveEvents.ts`).

`activity.in_play_fixtures` contains fixture ids whose captured `started` is
true and `finished` is false. Each appearance identifies an element and fixture,
with non-negative integer minutes, goals and assists taken from that element's
per-fixture `explain` statistics. Absent entries in the sparse statistic list
mean zero; missing or inconsistent explanation data means `activity: null`.
The embedded score remains available. Unknown or duplicate fixture identities,
duplicate event counters, and totals that disagree with the element's aggregate
statistics are refused as activity evidence.

Readers also reject duplicate element/fixture pairs, an in-play fixture marked
finished, unknown identities and appearance minutes that do not sum to each
element's gameweek minutes. Identifiers are season element ids, never persistent
player codes. The schema and all examples are synthetic.

The member card shows only that member's picks. Its static match indicator means
the player has recorded minutes in a match still in progress. FPL's aggregate
minutes do not establish whether a player has since been substituted, so the
accessible label is "Match in Progress", never "On the pitch".

Goals and assists are current realized counts. A first read establishes a
baseline without animation. A strictly newer source document can trigger one
400 ms highlight when a per-player, per-fixture counter exceeds its previously
seen maximum. Duplicate reads, older cache copies, downward corrections and a
correction restored to an already-seen value do not replay. Changing the member,
season or gameweek resets the baseline. Reduced motion shows the same counts
instantly, with no highlight animation and no looping pulse.
