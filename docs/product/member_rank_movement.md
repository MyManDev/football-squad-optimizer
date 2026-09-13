# Captured league rank movement

The members page reads both `rank` and `last_rank` from the same captured standings
document. It publishes the existing `movement` and `movement_places` fields. Neither
the member's points nor the registry order is used to reconstruct a previous rank.

- Positive previous and current ranks: subtract current from previous. Positive means
  `up`, negative means `down`; publish the absolute number of places.
- Equal positive ranks: `same` and `0`, displayed as “unchanged” / “yerinde kaldı”.
- Missing, null or zero previous rank: `unknown` and `null`, displayed as “Previous
  rank unavailable” / “Önceki sıra bilinmiyor”. Zero is not a position and does not
  prove that the member just joined. A missing current rank also prevents movement.
- Negative, boolean, fractional or text previous ranks fail parsing instead of being
  coerced into a plausible movement. Both standings parsers use the same rule.

The movement compares the game's current and previous weekly standings in the capture.
The adjacent scores come from the last completed and checked gameweek's member history.
The page states this distinction in Turkish and English; its upcoming advice gameweek
does not relabel the standings or their points.

## Captured source check for #533

The local capture `fpl-live-20260912T100000Z-24613792ef57` contains
`payloads/league-352490-standings.json`, stamped `last_updated_data:
2026-09-12T09:59:22Z`. All fifteen rows have a positive integer `last_rank`:
there is no missing, null or zero example in this league's captured rows. The leader's
record is `last_rank: 2, rank: 1`; an unchanged record is `12, 12`. The parser and
publisher read these as eight rises, six falls and one unchanged rank. The bootstrap
identifies GW3 as current and checked, and GW4 as next.

This capture does not establish which sentinel FPL emits for a newly joined member.
Synthetic tests cover absent, null and zero previous ranks for that case. None is
rendered as an ascent, descent or unchanged position. Private captures and member names
are not copied into the repository.

## Contract checks

`docs/contracts/league_member_movement_v1.schema.json` validates these existing member-row
fields, and the `PUBLISHABLE_FIELDS` catalogue names both. Up/down requires a positive
integer distance; unchanged requires zero; unknown/new requires null. The browser
validates the same combinations and its rendering fallback never shows “up zero”.
The publication and wording tests enforce this contract in both languages. The existing
test that a member's advice is invariant to every other member's state is unchanged.
