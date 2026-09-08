/**
 * What the URL asks for, as an advice request: strategy and window from the shared
 * selection, the rival only when it names a real other member of the league — or, for
 * a strategy that needs one and none was named, the producer's default rival (the
 * standings neighbour). The panel and the page read the same selection through this one
 * function, so the request that is sent and the request a result is checked against
 * cannot drift apart.
 *
 * The window is the one axis the URL can carry across a strategy change, so a page
 * passes its selection through `publishedSelection` first: the request then names a week
 * the index says exists rather than a file nobody wrote.
 */

import { isPlayMode, type WindowSize } from "../../moves/modePrices";
import {
  isMemberStrategy,
  strategyNeedsRival,
  type AdviceStrategy,
  type EntryAdviceIndex,
  type EntryView,
} from "../types";
import type { AdviceRequest } from "./adviceClient";

/**
 * The windows the producer published for a strategy, from the index. A tree from
 * before the windows existed, or no index at all, names window one only — the page
 * never offers a window nobody computed.
 */
export function availableWindows(
  index: EntryAdviceIndex | null | undefined,
  strategy: AdviceStrategy,
): WindowSize[] {
  return index?.windows?.[strategy] ?? [1];
}

/** The members a rival can be chosen from: the league's other human entries. */
export function rivalCandidates(members: EntryView[], entryId: number): EntryView[] {
  return members.filter((member) => member.member_kind === "human" && member.entry_id !== entryId);
}

/** The window the URL asks for, before the index has had a say. */
export function requestedWindow(searchParams: URLSearchParams): WindowSize {
  const raw = Number(searchParams.get("window"));
  return raw === 3 ? 3 : raw === 5 ? 5 : 1;
}

/**
 * The window the page can answer for a strategy: the one asked for where the index lists
 * it, and otherwise the first window the index does list. A window chosen under pure
 * points and carried into a rival strategy would otherwise address a file the producer
 * never wrote — every rival strategy is published at one week. An index that lists nothing
 * for a strategy — none published, or a legacy play mode the index does not govern —
 * leaves the selection as it stands.
 */
export function publishedWindow(
  requested: WindowSize,
  index: EntryAdviceIndex | null | undefined,
  strategy: AdviceStrategy,
): WindowSize {
  const windows = index?.windows?.[strategy];
  if (!windows || windows.length === 0 || windows.includes(requested)) return requested;
  return windows[0] ?? requested;
}

/**
 * The URL's selection with its window clamped to one the index publishes, so the control
 * and the request read the same week and neither can name a file the other would not.
 */
export function publishedSelection(
  searchParams: URLSearchParams,
  index: EntryAdviceIndex | null | undefined,
): URLSearchParams {
  const next = new URLSearchParams(searchParams);
  const window = publishedWindow(requestedWindow(searchParams), index, selectedStrategy(next));
  next.set("window", String(window));
  return next;
}

function selectedStrategy(searchParams: URLSearchParams): AdviceStrategy {
  const rawMode = searchParams.get("mode");
  return isMemberStrategy(rawMode) ? rawMode : isPlayMode(rawMode) ? rawMode : "saf-puan";
}

export function selectedAdviceRequest(
  searchParams: URLSearchParams,
  leagueId: number,
  entryId: number,
  members: EntryView[],
  context?: { season: string; gameweek: number },
  defaultRivalEntryId: number | null = null,
): AdviceRequest {
  const strategy: AdviceStrategy = selectedStrategy(searchParams);
  const window: WindowSize = requestedWindow(searchParams);
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
 * The combinations connected to the application compute path: pure points at any of
 * its windows, or a one-week member strategy with a rival named. A rival strategy at a
 * longer window and the legacy play modes are shown from the published tree only.
 */
export function canComputeAdvice(request: AdviceRequest): boolean {
  if (request.strategy === "saf-puan") return true;
  if (request.window !== 1) return false;
  return isMemberStrategy(request.strategy) && request.rivalEntryId != null;
}
