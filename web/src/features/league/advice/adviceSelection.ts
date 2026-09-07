/**
 * What the URL asks for, as an advice request: strategy and window from the shared
 * selection, the rival only when it names a real other member of the league — or, for
 * a strategy that needs one and none was named, the producer's default rival (the
 * standings neighbour), so the request always names the file the producer wrote. The
 * panel and the page read the same selection through this one function, so the request
 * that is sent and the request a result is checked against cannot drift apart.
 */

import { isPlayMode, type WindowSize } from "../../moves/modePrices";
import {
  isMemberStrategy,
  strategyNeedsRival,
  type AdviceStrategy,
  type EntryView,
} from "../types";
import type { AdviceRequest } from "./adviceClient";

/** The members a rival can be chosen from: the league's other human entries. */
export function rivalCandidates(members: EntryView[], entryId: number): EntryView[] {
  return members.filter((member) => member.member_kind === "human" && member.entry_id !== entryId);
}

export function selectedAdviceRequest(
  searchParams: URLSearchParams,
  leagueId: number,
  entryId: number,
  members: EntryView[],
  context?: { season: string; gameweek: number },
  defaultRivalEntryId: number | null = null,
): AdviceRequest {
  const rawMode = searchParams.get("mode");
  const strategy: AdviceStrategy = isMemberStrategy(rawMode)
    ? rawMode
    : isPlayMode(rawMode)
      ? rawMode
      : "saf-puan";
  const rawWindow = Number(searchParams.get("window"));
  const window: WindowSize = rawWindow === 3 ? 3 : rawWindow === 5 ? 5 : 1;
  const candidates = rivalCandidates(members, entryId);
  const isCandidate = (id: number) =>
    Number.isInteger(id) && candidates.some((member) => member.entry_id === id);
  const rawRival = Number(searchParams.get("rival"));
  let rivalEntryId: number | null = null;
  if (strategy !== "saf-puan" && isCandidate(rawRival)) {
    rivalEntryId = rawRival;
  } else if (
    strategyNeedsRival(strategy) &&
    defaultRivalEntryId !== null &&
    isCandidate(defaultRivalEntryId)
  ) {
    rivalEntryId = defaultRivalEntryId;
  }
  return { leagueId, entryId, strategy, window, rivalEntryId, ...context };
}

/**
 * The combinations connected to the application compute path: one-week plans — pure
 * points, or a member strategy with a rival named. Longer windows and the legacy play
 * modes are shown from the published tree only.
 */
export function canComputeAdvice(request: AdviceRequest): boolean {
  if (request.window !== 1) return false;
  if (request.strategy === "saf-puan") return true;
  return isMemberStrategy(request.strategy) && request.rivalEntryId != null;
}
