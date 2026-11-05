import type { EntryView, HumanEntryView, Scoreboard } from "../types";

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
 * (finished and checked), each human member's place. Where the league table publishes a
 * place, the race takes it: the table's `rank` for its scored gameweek, and the week before
 * from that rank and the table's `movement_places`, so the race and the table never show a
 * member two places for one week. The standings behind the table break equal totals; for
 * the weeks before those two the scoreboard publishes only totals, so a member's place is
 * one plus the members with a higher total, and equal totals share it. Nothing is taken
 * from a week that has not settled. Null without two settled weeks, when there is no race
 * to draw.
 */
export function leagueRace(
  scoreboard: Scoreboard,
  members: readonly EntryView[],
  scoredGameweek: number | null = null,
): LeagueRace | null {
  const humans = members.filter(
    (member): member is HumanEntryView =>
      member.member_kind === "human" && member.entry_id !== null,
  );
  const known = new Set(humans.map((member) => member.entry_id));
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

  // The table's own places for its scored gameweek and the one before it.
  const last = weeks.length - 1;
  if (scoredGameweek !== null && weeks[last]!.gameweek === scoredGameweek) {
    const previous = weeks[last - 1]!.gameweek === scoredGameweek - 1 ? placed[last - 1]! : null;
    for (const member of humans) {
      if (!Number.isSafeInteger(member.rank) || member.rank < 1) continue;
      if (!placed[last]!.totals.has(member.entry_id)) continue;
      placed[last]!.ranks.set(member.entry_id, member.rank);
      const before = placeBefore(member);
      if (previous && before !== null && previous.totals.has(member.entry_id))
        previous.ranks.set(member.entry_id, before);
    }
  }

  const lines = humans.map(({ entry_id: entryId }) => ({
    entryId,
    ranks: placed.map(({ ranks }) => ranks.get(entryId) ?? null),
    totals: placed.map(({ totals }) => totals.get(entryId) ?? null),
  }));
  const lastPlace = (line: RaceLine) =>
    line.ranks[line.ranks.length - 1] ?? Number.POSITIVE_INFINITY;
  lines.sort((a, b) => lastPlace(a) - lastPlace(b) || a.entryId - b.entryId);
  const places = Math.max(
    1,
    ...lines.flatMap((line) => line.ranks.filter((rank): rank is number => rank !== null)),
  );
  return { gameweeks: weeks.map((week) => week.gameweek), lines, places };
}

/** The table's place for the week before its scored one, from its rank and movement. */
function placeBefore(member: HumanEntryView): number | null {
  const places = member.movement_places;
  if (member.movement === "same") return member.rank;
  if (places === null || !Number.isSafeInteger(places) || places < 0) return null;
  if (member.movement === "up") return member.rank + places;
  if (member.movement === "down" && member.rank - places >= 1) return member.rank - places;
  return null;
}

/** A member's place and total after the latest settled week, and the points to each neighbour. */
export interface RaceGap {
  entryId: number;
  place: number;
  total: number;
  /** Points behind the member just ahead; null for the leader. */
  ahead: number | null;
  /** Points ahead of the member just behind; null for the last. */
  behind: number | null;
}

/**
 * Each member's gap to the member just ahead and the member just behind after the latest
 * settled week, from the totals the scoreboard publishes for that week, in the race's order
 * for it. A member without a row that week has no total and is left out. Equal totals are a
 * gap of 0. Where the order puts a higher total behind a lower one (places not ordered by
 * these totals), there is no distance to state, and that gap is null rather than negative.
 */
export function neighbourGaps(race: LeagueRace): RaceGap[] {
  const last = race.gameweeks.length - 1;
  const standing = race.lines.flatMap(({ entryId, ranks, totals }) => {
    const place = ranks[last];
    const total = totals[last];
    return place == null || total == null ? [] : [{ entryId, place, total }];
  });
  const gap = (higher: { total: number } | undefined, lower: { total: number } | undefined) =>
    higher && lower && higher.total >= lower.total ? higher.total - lower.total : null;
  return standing.map((member, index) => ({
    ...member,
    ahead: gap(standing[index - 1], member),
    behind: gap(member, standing[index + 1]),
  }));
}

/** Places gained in the week at `index` against the week before; negative when lost. */
export function placesMoved(line: RaceLine, index: number): number | null {
  if (index < 1) return null;
  const before = line.ranks[index - 1];
  const after = line.ranks[index];
  return before == null || after == null ? null : before - after;
}
