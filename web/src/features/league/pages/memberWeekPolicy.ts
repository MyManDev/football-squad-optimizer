import { weekState } from "../../../lib/weekState";
import type { FixturesPayload } from "../../fixtures/types";
import type { EntrySquad, Scoreboard } from "../types";

/** Same-season inputs and published row identities for the member page and league bar. */
export function memberWeekPolicy(
  squad: Pick<EntrySquad, "gameweek" | "season" | "league_id">,
  fixtures: FixturesPayload | null | undefined,
  scoreboard: Scoreboard | null | undefined,
  now: number,
) {
  const calendar = fixtures?.season === squad.season ? fixtures : null;
  const events =
    scoreboard?.season === squad.season && scoreboard.league_id === squad.league_id
      ? scoreboard.gameweeks
      : [];
  const published = [squad.gameweek];
  return weekState({
    treeGameweek: squad.gameweek,
    events,
    fixtures: calendar,
    now,
    current: {
      topBar: squad.gameweek,
      plan: squad.gameweek,
      resources: squad.gameweek,
      memberRail: squad.gameweek,
    },
    available: {
      topBar: published,
      plan: published,
      resources: published,
      memberRail: calendar?.gameweeks.map((week) => week.gameweek) ?? [],
    },
  });
}
