import type { EntryAdviceIndex } from "../features/league/types";

// The index the producer writes for a member it could not advise this week, mirrored from
// `_refused_member_index` in `src/squadopt/application/league_views.py`: every declared
// strategy listed with pure points first, nothing computed, no window promised for any
// strategy, no suggestion, and the one reason once per strategy with no rival and no window.
// No squad is published beside it and the member list reports the member's data as empty.
// The page accepts it through the ordinary index validator and shows the reason where the
// squad would be, so a tree holding one is honest, not broken. A reason the copy knows is
// shown as the copy's sentence in the reader's language, never as written: a plan the
// planner or solver could not produce is published as the code `not_solved_for_member`.
// Any other reason is shown as written.

export const REFUSED_STRATEGIES = ["saf-puan", "ortak-koru", "fark-yarat"] as const;

export function refusedMemberIndex({
  leagueId,
  season,
  gameweek,
  entryId,
  rivalEntryIds,
  defaultRivalEntryId = rivalEntryIds[0] ?? null,
  reason,
  strategies = [...REFUSED_STRATEGIES],
}: {
  leagueId: number;
  season: string;
  gameweek: number;
  entryId: number;
  rivalEntryIds: number[];
  defaultRivalEntryId?: number | null;
  reason: string;
  strategies?: string[];
}): EntryAdviceIndex {
  return {
    league_id: leagueId,
    season,
    gameweek,
    entry_id: entryId,
    window: 1,
    windows: Object.fromEntries(strategies.map((strategy) => [strategy, []])),
    strategies,
    rival_entry_ids: rivalEntryIds,
    default_rival_entry_id: defaultRivalEntryId,
    suggested_strategy: null,
    computed: [],
    unavailable: strategies.map((strategy) => ({ strategy, rival_entry_id: null, reason })),
  };
}

export function isRefusedMemberIndex(index: EntryAdviceIndex): boolean {
  const reason = index.unavailable[0]?.reason;
  return (
    index.strategies[0] === "saf-puan" &&
    index.computed.length === 0 &&
    index.suggested_strategy === null &&
    index.windows !== undefined &&
    Object.keys(index.windows).join() === index.strategies.join() &&
    Object.values(index.windows).every((windows) => windows?.length === 0) &&
    index.unavailable.length === index.strategies.length &&
    index.unavailable.every(
      (row, position) =>
        row.strategy === index.strategies[position] &&
        row.rival_entry_id === null &&
        row.window === undefined &&
        row.reason === reason,
    )
  );
}
