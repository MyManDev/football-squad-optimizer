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
  const fixture = row.fixture;
  const minutes = fixture.minutes ?? (row.fixtures.length === 1 ? row.minutes : null);
  const when =
    row.fact === "didNotPlay"
      ? copy.didNotPlay
      : fixture.phase === "upcoming" && (minutes ?? 0) === 0
        ? fixture.kickoff === null
          ? null
          : kickoffShort(fixture.kickoff, locale)
        : minutes === null
          ? null
          : copy.minutes(wholePoints(minutes, locale));
  return [fixture.opponent, when].filter((part): part is string => part !== null).join(" · ");
}

/** What a pick's row says to a screen reader: name, role, group, points, events and state. */
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
  const events = [
    row.goals > 0 ? `${live.goal} ${wholePoints(row.goals, locale)}` : null,
    row.assists > 0 ? `${live.assist} ${wholePoints(row.assists, locale)}` : null,
    row.card ? live.card : null,
  ];
  const state =
    row.fact === "noMatch"
      ? live.noMatch
      : row.fact === "didNotPlay"
        ? live.didNotPlay
        : row.state === "up"
          ? live.doingWell
          : row.state === "down"
            ? live.struggling
            : null;
  return [
    row.name,
    ...roles,
    live.groups[row.group],
    row.started ? live.points(wholePoints(rowPoints(row), locale)) : null,
    ...events,
    state,
  ]
    .filter((part): part is string => part !== null)
    .join(", ");
}
