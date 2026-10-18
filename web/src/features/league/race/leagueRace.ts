import type { EntryView, Scoreboard } from "../types";

/** One member's place after each settled gameweek, and the total it stands on. */
export interface RaceLine {
  entryId: number;
  /** The place after each gameweek of `LeagueRace.gameweeks`; null where the week has no row. */
  ranks: (number | null)[];
  totals: (number | null)[];
}

export interface LeagueRace {
  /** The settled gameweeks, in order. */
  gameweeks: number[];
  /** Every human member's line, in the order of the last week's table. */
  lines: RaceLine[];
  /** The lowest place any week has, so every line fits. */
  places: number;
}

/**
 * The league race (#1135) from the published scoreboard: after each settled gameweek
 * (finished and checked), each human member's place by the total the scoreboard publishes
 * for that week, a higher total ahead and an equal total sharing the place. Nothing is
 * taken from a week that has not settled, and nothing is computed beyond the order of the
 * published totals. Null without two settled weeks, when there is no race to draw.
 */
export function leagueRace(
  scoreboard: Scoreboard,
  members: readonly EntryView[],
): LeagueRace | null {
  const humans = members
    .filter((member) => member.member_kind === "human" && member.entry_id !== null)
    .map((member) => member.entry_id!);
  const known = new Set(humans);
  const weeks = scoreboard.gameweeks
    .filter((week) => week.finished && week.data_checked)
    .sort((a, b) => a.gameweek - b.gameweek);
  if (weeks.length < 2 || humans.length === 0) return null;

  const placed = weeks.map((week) => {
    const totals = new Map<number, number>();
    for (const row of week.members) {
      if (known.has(row.entry_id) && Number.isFinite(row.total_points))
        totals.set(row.entry_id, row.total_points);
    }
    const ranks = new Map<number, number>();
    for (const [entryId, total] of totals) {
      let ahead = 0;
      for (const other of totals.values()) if (other > total) ahead += 1;
      ranks.set(entryId, ahead + 1);
    }
    return { totals, ranks };
  });

  const lines = humans.map((entryId) => ({
    entryId,
    ranks: placed.map(({ ranks }) => ranks.get(entryId) ?? null),
    totals: placed.map(({ totals }) => totals.get(entryId) ?? null),
  }));
  const last = (line: RaceLine) => line.ranks[line.ranks.length - 1] ?? Number.POSITIVE_INFINITY;
  lines.sort((a, b) => last(a) - last(b) || a.entryId - b.entryId);
  const places = Math.max(
    1,
    ...lines.flatMap((line) => line.ranks.filter((rank): rank is number => rank !== null)),
  );
  return { gameweeks: weeks.map((week) => week.gameweek), lines, places };
}

/** Places gained in the week at `index` against the week before; negative when lost. */
export function placesMoved(line: RaceLine, index: number): number | null {
  if (index < 1) return null;
  const before = line.ranks[index - 1];
  const after = line.ranks[index];
  return before == null || after == null ? null : before - after;
}
