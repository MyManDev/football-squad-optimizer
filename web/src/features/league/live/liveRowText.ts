/**
 * What a LIVE row says in words: the line under the player's name, and the name a screen
 * reader gives the row. Display only: every number comes scored from the board.
 */

import type { Messages } from "../../../i18n/messages";
import { rowPoints, type LiveRow } from "./liveBoard";
import { kickoffShort, wholePoints } from "./liveFormat";

/**
 * The opponent, then the kickoff before the match or the minutes once it has started. A
 * double week read without event detail has no minutes per match, and the week's minutes are
 * not one match's, so its fixture shows its kickoff before it and no minutes after.
 */
export function subLine(row: LiveRow, copy: Messages["live"], locale: string): string {
  if (row.fact === "noMatch" || row.fixture === null) return copy.noMatch;
  const time = row.fact === "didNotPlay" ? copy.didNotPlay : when(row, copy, locale);
  return [row.fixture.opponent, time].filter((part): part is string => part !== null).join(" · ");
}

/** The kickoff before the match, or the minutes once it has started; null where neither is known. */
function when(row: LiveRow, copy: Messages["live"], locale: string): string | null {
  const fixture = row.fixture;
  if (fixture === null) return null;
  const minutes = fixture.minutes ?? (row.fixtures.length === 1 ? row.minutes : null);
  if (fixture.phase === "upcoming" && (minutes ?? 0) === 0) {
    return fixture.kickoff === null ? null : kickoffShort(fixture.kickoff, locale);
  }
  return minutes === null ? null : copy.minutes(wholePoints(minutes, locale));
}

/**
 * What a pick's row says to a screen reader: name, role, group, its match (the opponent, the
 * kickoff or the minutes, as the line under the name shows), points, events and state.
 */
export function rowLabel(row: LiveRow, copy: Messages, locale: string): string {
  const live = copy.live;
  const roles: string[] = [];
  if (row.armband === "captain") {
    roles.push(
      row.multiplier >= 2
        ? `${copy.leagueMembers.captainLabel} ×${row.multiplier}`
        : copy.leagueMembers.captainLabel,
    );
  } else if (row.armband === "vice") {
    roles.push(copy.leagueMembers.viceCaptainLabel);
  }
  if (row.autosub !== null) {
    roles.push(row.autosub === "in" ? copy.leagueMembers.in : copy.leagueMembers.out);
  }
  // A pick the scorer does not count brings the member nothing: none of its events or its
  // state is told (the owner's word of 2026-11-11); under the bench boost the bench counts.
  const events = row.counted
    ? [
        row.goals > 0 ? `${live.goal} ${wholePoints(row.goals, locale)}` : null,
        row.assists > 0 ? `${live.assist} ${wholePoints(row.assists, locale)}` : null,
        row.card ? live.card : null,
      ]
    : [];
  const state =
    row.fact === "noMatch"
      ? live.noMatch
      : row.fact === "didNotPlay"
        ? live.didNotPlay
        : !row.counted
          ? null
          : row.state === "up"
            ? live.doingWell
            : row.state === "down"
              ? live.struggling
              : null;
  // Oynamadı and Maç yok are the row's state, said below, not its match.
  const match =
    row.fact === "noMatch" || row.fixture === null
      ? []
      : [row.fixture.opponent, row.fact === "didNotPlay" ? null : when(row, live, locale)];
  return [
    row.name,
    ...roles,
    live.groups[row.group],
    ...match,
    row.started ? live.points(wholePoints(rowPoints(row), locale)) : null,
    ...events,
    state,
  ]
    .filter((part): part is string => part !== null)
    .join(", ");
}
