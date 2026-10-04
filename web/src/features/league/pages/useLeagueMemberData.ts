import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import type { ComputeService } from "../advice/AdviceRequestPanel";
import { capabilitiesForPage } from "../advice/adviceCapabilities";
import { createAdviceClient } from "../advice/adviceClient";
import { resolvePublishedAdvice, rivalCandidates } from "../advice/adviceSelection";
import { checkedAdvice } from "../advice/adviceResponse";
import { offeredDeviceSelection } from "../device/selection";
import { isDevicePlanEntry } from "../device/types";
import type { EntryView } from "../types";
import { useLeague } from "../useLeague";
import {
  CAPABILITIES_READ,
  LEAGUE_READ,
  leagueKeys,
  useEntrySquad,
  useEntrySquads,
  useLeagueMembers,
} from "../queries";
import { deviceRequestFor, memberSelection } from "./memberSelection";

/** The other human members' entry ids: the rivals a rival strategy may name. */
function rivalCandidateIds(members: EntryView[], entryId: number): number[] {
  return rivalCandidates(members, entryId)
    .map((member) => member.entry_id)
    .filter((id): id is number => typeof id === "number");
}

/** Read only the publication authorized by the current member index and URL. */
export function useLeagueMemberData(entryParam: string | undefined, searchParams: URLSearchParams) {
  const entryId = Number(entryParam);
  const validEntryId = Number.isSafeInteger(entryId) && entryId > 0;
  const { league, tree } = useLeague();
  const squad = useEntrySquad(entryId, validEntryId);
  const membersQuery = useLeagueMembers();
  // The index says which (strategy, rival) files the producer wrote for this member; a
  // missing or unreadable index cannot authorize a guessed baseline read.
  const indexQuery = useQuery({
    queryKey: leagueKeys.adviceIndex(league.leagueId, entryId),
    queryFn: () => tree.entryAdviceIndex(entryId),
    enabled: validEntryId,
    ...LEAGUE_READ,
  });
  const members = membersQuery.data?.payload.members ?? [];
  const index = indexQuery.isError ? null : (indexQuery.data?.payload ?? null);
  // A build with no compute service has a client that cannot be asked, and this query
  // never runs: the page is the static site. With one, what it computes right now is read
  // on entry and again on focus once stale. A service that is down, slow or answering
  // for another capture leaves the page on the published tree with a notice, never an error.
  const client = useMemo(() => createAdviceClient(tree.entryAdvice), [tree]);
  const leagueId = squad.data?.payload.league_id;
  const canAsk = client.readCapabilities !== undefined;
  const capabilitiesQuery = useQuery({
    queryKey: ["advice-capabilities", leagueId],
    queryFn: ({ signal }) => client.readCapabilities!(leagueId!, { signal }),
    enabled: validEntryId && canAsk && leagueId !== undefined,
    ...CAPABILITIES_READ,
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
  // The other members' entry documents, read where the publish wrote this member's device
  // inputs: the device offers a rival strategy only against a rival whose document it can
  // use, and the view is handed the same documents to make the same statement from.
  const ownSquad = squad.data?.payload;
  const deviceInputs = isDevicePlanEntry(ownSquad?.device_plan) && !!ownSquad?.source_snapshot_id;
  const deviceRivals = useEntrySquads(
    ownSquad ? rivalCandidateIds(members, ownSquad.entry.entry_id) : [],
    deviceInputs,
  );
  // One resolver for the page's reads and its view, so the rival read here is the rival
  // the view selects and the device solves against.
  const resolved = ownSquad
    ? memberSelection({ squad: ownSquad, members, index, capabilities, deviceRivals })
    : null;
  const selection = resolved
    ? resolved.resolve(searchParams)
    : resolvePublishedAdvice(searchParams, 0, entryId, members, index);
  const { request } = selection;
  // The rival a device solve of this selection is played against, where the device's
  // statement offers the selection; the card compares the plan with that rival's squad.
  const deviceSolve =
    ownSquad && resolved?.onDevice
      ? offeredDeviceSelection(deviceRequestFor(selection), ownSquad, resolved.onDevice.rivals)
      : null;
  const adviceEnabled = validEntryId && !!squad.data && selection.status === "ready";

  const advice = useQuery({
    queryKey: [
      "provisional-entry-advice",
      league.leagueId,
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
        ? tree.entryAdviceChip(entryId, selection.path, selection.chip.chip, { signal })
        : selection.top100.weight !== 0 && selection.path
          ? tree.entryAdviceTop100(
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
            ? tree.entryAdviceEvidence(entryId, selection.path, { signal })
            : tree.entryAdvice(
                entryId,
                request.strategy,
                request.window,
                request.rivalEntryId ?? null,
                { signal },
              ),
    enabled: adviceEnabled,
    ...LEAGUE_READ,
  });

  const controlSelection = resolvePublishedAdvice(
    new URLSearchParams(`mode=saf-puan&window=${request.window}`),
    leagueId ?? 0,
    entryId,
    members,
    index,
    squad.data
      ? { season: squad.data.payload.season, gameweek: squad.data.payload.gameweek }
      : undefined,
  );
  const windowControl = useQuery({
    queryKey: [
      "published-window-control",
      league.leagueId,
      entryId,
      request.window,
      request.season,
      request.gameweek,
      squad.data?.payload.source_snapshot_id,
      controlSelection.path,
    ],
    queryFn: async ({ signal }) =>
      checkedAdvice(
        await tree.entryAdvice(entryId, "saf-puan", request.window, null, { signal }),
        controlSelection.request,
      ),
    enabled:
      validEntryId &&
      !!squad.data &&
      (selection.status === "ready" || selection.computable?.selection === true) &&
      request.window > 1 &&
      (request.strategy !== "saf-puan" || selection.top100.weight !== 0) &&
      controlSelection.status === "ready" &&
      controlSelection.request.window === request.window,
    ...LEAGUE_READ,
  });

  // A rival the service can be asked about, or the device solves against, is shown beside
  // the computed plan as well.
  const rival = useEntrySquad(
    request.rivalEntryId,
    adviceEnabled ||
      (!!squad.data && selection.computable?.selection === true) ||
      deviceSolve?.kind === "rival",
  );

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
    deviceRivals,
    windowControl,
    client,
    capabilities,
    computeService,
    computePending,
  };
}
