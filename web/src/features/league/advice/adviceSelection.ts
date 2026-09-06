/**
 * What the URL asks for, as an advice request: strategy and window from the shared
 * selection, the rival only when it names a real other member of the league. The panel
 * and the page read the same selection through this one function, so the request that
 * is sent and the request a result is checked against cannot drift apart.
 */

import { isPlayMode, type PlayMode, type WindowSize } from "../../moves/modePrices";
import type { EntryView } from "../types";
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
): AdviceRequest {
  const strategy: PlayMode = isPlayMode(searchParams.get("mode"))
    ? (searchParams.get("mode") as PlayMode)
    : "saf-puan";
  const rawWindow = Number(searchParams.get("window"));
  const window: WindowSize = rawWindow === 3 ? 3 : rawWindow === 5 ? 5 : 1;
  const rawRival = Number(searchParams.get("rival"));
  const rivalEntryId =
    Number.isInteger(rawRival) &&
    rivalCandidates(members, entryId).some((member) => member.entry_id === rawRival)
      ? rawRival
      : null;
  return { leagueId, entryId, strategy, window, rivalEntryId };
}
