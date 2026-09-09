import { useQuery } from "@tanstack/react-query";

import { resolvePublishedAdvice } from "../advice/adviceSelection";
import { loadEntryAdvice, loadEntryAdviceIndex, loadEntrySquad, loadLeagueMembers } from "../data";

/** Read only the publication authorized by the current member index and URL. */
export function useLeagueMemberData(entryParam: string | undefined, searchParams: URLSearchParams) {
  const entryId = Number(entryParam);
  const validEntryId = Number.isSafeInteger(entryId) && entryId > 0;
  const squad = useQuery({
    queryKey: ["provisional-entry-squad", entryId],
    queryFn: () => loadEntrySquad(entryId),
    enabled: validEntryId,
    staleTime: 60_000,
  });
  const membersQuery = useQuery({
    queryKey: ["provisional-league-members"],
    queryFn: loadLeagueMembers,
    staleTime: 60_000,
  });
  // The index says which (strategy, rival) files the producer wrote for this member; a
  // missing or unreadable index cannot authorize a guessed baseline read.
  const indexQuery = useQuery({
    queryKey: ["provisional-entry-advice-index", entryId],
    queryFn: () => loadEntryAdviceIndex(entryId),
    enabled: validEntryId,
    staleTime: 60_000,
    retry: false,
  });
  const members = membersQuery.data?.payload.members ?? [];
  const index = indexQuery.isError ? null : (indexQuery.data?.payload ?? null);
  const selection = resolvePublishedAdvice(
    searchParams,
    squad.data?.payload.league_id ?? 0,
    entryId,
    members,
    index,
    squad.data
      ? {
          season: squad.data.payload.season,
          gameweek: squad.data.payload.gameweek,
        }
      : undefined,
  );
  const { request } = selection;
  const adviceEnabled = validEntryId && !!squad.data && selection.status === "ready";

  const advice = useQuery({
    queryKey: [
      "provisional-entry-advice",
      entryId,
      request.strategy,
      request.window,
      request.rivalEntryId,
      selection.path,
      request.season,
      request.gameweek,
      squad.data?.payload.source_snapshot_id,
    ],
    queryFn: ({ signal }) =>
      loadEntryAdvice(entryId, request.strategy, request.window, request.rivalEntryId ?? null, {
        signal,
      }),
    enabled: adviceEnabled,
    staleTime: 60_000,
  });

  const rival = useQuery({
    queryKey: ["provisional-entry-squad", request.rivalEntryId],
    queryFn: () => loadEntrySquad(request.rivalEntryId!),
    enabled: adviceEnabled && request.rivalEntryId != null,
    staleTime: 60_000,
    retry: false,
  });

  return {
    validEntryId,
    squad,
    membersQuery,
    indexQuery,
    members,
    index,
    selection,
    adviceEnabled,
    advice,
    rival,
  };
}
