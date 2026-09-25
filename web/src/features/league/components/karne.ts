import type { LeagueViewEnvelope, Scoreboard } from "../types";

/** The scoreboard document as the league table page holds it while it reads it. */
export type ScoreboardState =
  | { status: "pending" }
  | { status: "missing" }
  | { status: "error" }
  | { status: "ready"; envelope: LeagueViewEnvelope<Scoreboard> };

export interface KarneWeek {
  gameweek: number;
  provisional: boolean;
  /** The system's paper squad, net; null while the week has no settled system record. */
  ours: number | null;
  /** The system's week was recorded after its deadline, not decided live. */
  replay: boolean;
  /** The system's net counts its named eleven, with no autosubs or vice-captain step. */
  namedEleven: boolean;
  league: number | null;
  game: number | null;
}

/**
 * One line per finished gameweek, straight from the scoreboard: the system's paper squad,
 * the league members' mean and the game's average, each null where the document says
 * nothing. A missing system week stays missing ("no record"), never a bar of zero. A week
 * the system recorded after its deadline is marked replay, and the basis its net is on is
 * carried so the record can say it, as the full scoreboard does.
 */
export function karneWeeks(view: Scoreboard): KarneWeek[] {
  const value = (number: number | null | undefined) =>
    typeof number === "number" && Number.isFinite(number) ? number : null;
  return view.gameweeks
    .filter((week) => week.finished)
    .map((week) => ({
      gameweek: week.gameweek,
      provisional: !week.data_checked,
      ours: value(week.ours?.net),
      replay: week.ours?.mode === "replay",
      namedEleven: week.ours?.scoring_basis === "named_eleven_no_autosubs",
      league: value(week.members_mean_net),
      game: value(week.average_entry_score),
    }));
}
