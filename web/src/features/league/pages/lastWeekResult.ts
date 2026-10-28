import type { SuggestionHistory } from "../history/historyData";
import type { EntrySquad, Scoreboard, ScoreboardGameweek } from "../types";

/** The rank movement the member's standing states: a count of places, or unchanged. */
export type LastWeekMovement =
  { movement: "up" | "down"; places: number } | { movement: "same"; places: 0 };

/**
 * What the latest-week card on the member page says. Every figure is one a published file
 * states for that gameweek; a figure no file states is null, and the card leaves its line out.
 */
export interface LastWeekResult {
  gameweek: number;
  /** The week right before the one this page advises, so the card may call it last week. */
  previous: boolean;
  /** Finished but not yet data-checked: the scoreboard's provisional week. */
  provisional: boolean;
  /** The member's week net of the hits taken, from the scoreboard's own row for them. */
  net: number;
  movement: LastWeekMovement | null;
  /** The league members' mean net for that week and how many members it counts. */
  leagueMean: { mean: number; counted: number } | null;
  /** The game's own published average for that week. */
  gameAverage: number | null;
  /**
   * What the published one-week pure-points suggestion scored that week, net of its recorded
   * hits: the recorded squad scored with the settled results, official substitutions and
   * captain, and any chip it named.
   */
  suggested: number | null;
}

const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

/**
 * The member's latest finished gameweek, from the documents the page holds: the scoreboard
 * (the week, whether it is checked, the member's net, the league's mean net and the game's
 * average), the member's own squad document (the rank movement, only when its scored week
 * is that week) and the member's suggestion history (what the published suggestion scored,
 * only for a week the history settled). Null when there is no finished week, when the
 * scoreboard is another league's or season's, or when it states no net for this member: a
 * card about the member's week with no figure of the member's says nothing about them.
 */
export function lastWeekResult(
  squad: EntrySquad,
  scoreboard: Scoreboard | null,
  history: SuggestionHistory | null,
): LastWeekResult | null {
  if (
    scoreboard === null ||
    scoreboard.league_id !== squad.league_id ||
    scoreboard.season !== squad.season
  )
    return null;
  let week: ScoreboardGameweek | null = null;
  for (const row of scoreboard.gameweeks)
    if (row.finished && (week === null || row.gameweek > week.gameweek)) week = row;
  if (week === null) return null;
  const entryId = squad.entry.entry_id;
  const net = week.members.find((row) => row.entry_id === entryId)?.net;
  if (!finite(net)) return null;

  // The standing's movement compares the game's current and previous ranks; it is this
  // week's only when the squad document scored this week, and a provisional week is not
  // the one it scored.
  const { movement, movement_places: places } = squad.entry;
  const moved: LastWeekMovement | null =
    squad.scored_gameweek !== week.gameweek
      ? null
      : (movement === "up" || movement === "down") &&
          typeof places === "number" &&
          Number.isSafeInteger(places) &&
          places > 0
        ? { movement, places }
        : movement === "same" && places === 0
          ? { movement: "same", places: 0 }
          : null;

  // Only a week the history settled: the publisher scores the suggestion, and calls the week
  // available, only once the gameweek is finished and data-checked in a capture taken after
  // its deadline; before that the week is unsettled and carries no score. Another member's,
  // league's or season's history says nothing here.
  const recorded =
    history !== null &&
    history.payload.entry_id === entryId &&
    history.payload.league_id === squad.league_id &&
    history.payload.season === squad.season
      ? history.payload.weeks.find((row) => row.gameweek === week.gameweek)
      : undefined;
  const suggested =
    recorded?.status === "available" && finite(recorded.suggested?.net_points)
      ? recorded.suggested.net_points
      : null;

  return {
    gameweek: week.gameweek,
    previous: week.gameweek === squad.gameweek - 1,
    provisional: !week.data_checked,
    net,
    movement: moved,
    leagueMean:
      finite(week.members_mean_net) &&
      Number.isSafeInteger(week.members_counted) &&
      week.members_counted > 0
        ? { mean: week.members_mean_net, counted: week.members_counted }
        : null,
    gameAverage: finite(week.average_entry_score) ? week.average_entry_score : null,
    suggested,
  };
}
