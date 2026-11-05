import type { EntrySquad } from "../types";

/** A different member, capture, plan or account must never inherit a tried squad. */
export function whatIfBasis(squad: EntrySquad, advised: readonly number[]): string {
  return JSON.stringify([
    squad.league_id,
    squad.entry.entry_id,
    squad.season,
    squad.gameweek,
    squad.source_snapshot_id,
    advised,
    squad.device_plan,
  ]);
}

export function whatIfSlot(squad: EntrySquad): string {
  return `squadopt.what-if.${squad.league_id}.${squad.entry.entry_id}`;
}

/** Only player ids live in this tab; points are always recalculated from the current table. */
export function readWhatIfDraft(slot: string, basis: string): readonly number[] | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(slot) ?? "null") as unknown;
    if (!saved || typeof saved !== "object" || !("basis" in saved) || saved.basis !== basis)
      return null;
    if (!("players" in saved) || !Array.isArray(saved.players)) return null;
    const players: unknown[] = saved.players;
    if (
      players.length > 1000 ||
      !players.every((id) => typeof id === "number" && Number.isSafeInteger(id) && id > 0) ||
      new Set(players).size !== players.length
    )
      return null;
    return players as number[];
  } catch {
    return null;
  }
}

export function writeWhatIfDraft(slot: string, basis: string, players: readonly number[]): void {
  try {
    sessionStorage.setItem(slot, JSON.stringify({ basis, players }));
  } catch {
    // Storage can be disabled or full; the current page remains usable.
  }
}
