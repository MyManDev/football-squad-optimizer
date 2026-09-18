import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import type { ComputeService } from "../advice/AdviceRequestPanel";
import { capabilitiesForPage } from "../advice/adviceCapabilities";
import { createAdviceClient } from "../advice/adviceClient";
import { resolvePublishedAdvice } from "../advice/adviceSelection";
import {
  loadEntryAdvice,
  loadEntryAdviceChip,
  loadEntryAdviceEvidence,
  loadEntryAdviceIndex,
  loadEntryAdviceTop100,
  loadEntrySquad,
  loadLeagueMembers,
} from "../data";

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
  // A build with no compute service has a client that cannot be asked, and this query
  // never runs: the page is the static site. With one, what it computes right now is read
  // once; a service that is down, slow or answering for another capture leaves the page
  // on the published tree with a notice, never on an error.
  const client = useMemo(() => createAdviceClient(), []);
  const leagueId = squad.data?.payload.league_id;
  const canAsk = client.readCapabilities !== undefined;
  const capabilitiesQuery = useQuery({
    queryKey: ["advice-capabilities", leagueId],
    queryFn: ({ signal }) => client.readCapabilities!(leagueId!, { signal }),
    enabled: validEntryId && canAsk && leagueId !== undefined,
    staleTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const capabilities = squad.data
    ? capabilitiesForPage(capabilitiesQuery.data, {
        leagueId: squad.data.payload.league_id,
        season: squad.data.payload.season,
        gameweek: squad.data.payload.gameweek,
        snapshotId: squad.data.payload.source_snapshot_id,
      })
    : null;
  const computePending = canAsk && leagueId !== undefined && capabilitiesQuery.isPending;
  const computeService: ComputeService =
    !canAsk || capabilitiesQuery.isPending
      ? "static"
      : capabilitiesQuery.isError || !capabilitiesQuery.data
        ? "unreachable"
        : capabilities
          ? "ready"
          : "other-capture";
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
    capabilities,
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
      selection.evidence.on,
      selection.top100.weight,
      selection.chip.chip,
      request.season,
      request.gameweek,
      squad.data?.payload.source_snapshot_id,
    ],
    // With the manager's word switched on, the document is the one the index names; the
    // plain paths below would serve the plan solved without it under the same request.
    // A Top 100 weight reads its own document at the one path the index may name, and so
    // does a chip the member chose.
    queryFn: ({ signal }) =>
      selection.chip.chip !== null && selection.path
        ? loadEntryAdviceChip(entryId, selection.path, selection.chip.chip, { signal })
        : selection.top100.weight !== 0 && selection.path
          ? loadEntryAdviceTop100(
              entryId,
              selection.path,
              selection.top100.weight,
              selection.evidence.on,
              { signal },
              {
                strategy: request.strategy,
                window: request.window,
                rivalEntryId: request.rivalEntryId ?? null,
              },
            )
          : selection.evidence.on && selection.path
            ? loadEntryAdviceEvidence(entryId, selection.path, { signal })
            : loadEntryAdvice(
                entryId,
                request.strategy,
                request.window,
                request.rivalEntryId ?? null,
                { signal },
              ),
    enabled: adviceEnabled,
    staleTime: 60_000,
  });

  const rival = useQuery({
    queryKey: ["provisional-entry-squad", request.rivalEntryId],
    queryFn: () => loadEntrySquad(request.rivalEntryId!),
    // A rival the service can be asked about is shown beside the computed plan as well.
    enabled:
      (adviceEnabled || (!!squad.data && selection.computable?.selection === true)) &&
      request.rivalEntryId != null,
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
    client,
    capabilities,
    computeService,
    computePending,
  };
}
