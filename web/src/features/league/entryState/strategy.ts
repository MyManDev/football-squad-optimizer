/** Offline ports of choose_rival and gap_and_weeks_strategy_rule_v1. */
import type { EntryAdviceIndex } from "../types";
import { EntryStateError, integer } from "./parsers";

export const STRATEGY_RULE_ID = "gap_and_weeks_strategy_rule_v1";
export const WEEKLY_POINTS_DIFFERENTIAL_POINTS = 21.2;
const FINAL_GAMEWEEK = 38;

export interface StrategyInputs {
  rival_entry_id: number;
  points_ahead_of_rival: number;
  gameweek: number;
  scored_gameweek: number;
}

/** Candidates are eligible real members of the same league, excluding the member. */
export function chooseRival<T>(
  entryId: number,
  ranks: ReadonlyMap<number, number>,
  candidates: ReadonlyMap<number, T>,
): T | null {
  integer(entryId, "entry id", 1);
  if (candidates.has(entryId)) throw new EntryStateError("A member cannot be their own rival.");
  for (const [id, rank] of ranks) {
    integer(id, "ranked entry id", 1);
    integer(rank, "rank", 1);
  }
  for (const id of candidates.keys()) integer(id, "candidate entry id", 1);
  const ownRank = ranks.get(entryId);
  if (ownRank === undefined) return null;
  const ranked = [...ranks]
    .filter(([id]) => id !== entryId && candidates.has(id))
    .sort(([a, aRank], [b, bRank]) => aRank - bRank || a - b);
  const above = ranked.filter(([, rank]) => rank < ownRank);
  const picked = above.at(-1) ?? ranked[0];
  return picked === undefined ? null : candidates.get(picked[0])!;
}

export function suggestStrategy(
  input: StrategyInputs,
): NonNullable<EntryAdviceIndex["suggested_strategy"]> {
  integer(input.rival_entry_id, "rival entry id", 1);
  integer(input.points_ahead_of_rival, "points gap", Number.MIN_SAFE_INTEGER);
  integer(input.gameweek, "gameweek", 1);
  integer(input.scored_gameweek, "scored gameweek");
  const weeks = Math.max(0, FINAL_GAMEWEEK - input.gameweek + 1);
  // Python-exported vectors pin the rounded edge for every week of the season.
  const edge = Math.round(WEEKLY_POINTS_DIFFERENTIAL_POINTS * Math.sqrt(weeks) * 10) / 10;
  const gap = input.points_ahead_of_rival;
  const band = gap < -edge ? "behind" : gap > edge ? "ahead" : "level";
  const strategy = band === "behind" ? "fark-yarat" : band === "ahead" ? "ortak-koru" : "saf-puan";
  return {
    strategy,
    rule_id: STRATEGY_RULE_ID,
    band,
    rival_entry_id: input.rival_entry_id,
    points_ahead_of_rival: gap,
    scored_gameweek: input.scored_gameweek,
    gameweeks_remaining: weeks,
    band_edge_points: edge,
  };
}
