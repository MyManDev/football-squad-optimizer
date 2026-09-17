import { useEffect, useMemo, useRef } from "react";

import { createAdviceClient } from "../advice/adviceClient";
import { adviceRequestKey } from "../advice/adviceJobStore";
import { canComputeAdvice, resolvePublishedAdvice } from "../advice/adviceSelection";
import { AdviceContextError, checkedAdvice } from "../advice/adviceResponse";
import {
  ANSWER_OTHER_CAPTURE,
  sameAdviceRequest,
  useAdviceJob,
  type AdviceJob,
} from "../advice/useAdviceJob";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import type { LeagueMemberViewProps, ShownAdvice } from "./memberPageTypes";

/** Select/reset advice for the current URL while rejecting stale publication context. */
export function useMemberAdviceView(
  {
    squad,
    advice,
    adviceIssue,
    adviceLoading = false,
    members = [],
    index = null,
    client,
    capabilities = null,
    computeService = "static",
  }: LeagueMemberViewProps,
  searchParams: URLSearchParams,
) {
  const view = squad.payload;
  const adviceClient = useMemo(() => client ?? createAdviceClient(), [client]);
  const leagueId = view.league_id;
  const entryId = view.entry.entry_id;
  const resolve = (params: URLSearchParams) =>
    resolvePublishedAdvice(
      params,
      leagueId,
      entryId,
      members,
      index,
      { season: view.season, gameweek: view.gameweek },
      capabilities,
    );
  const selection = resolve(searchParams);
  const { request } = selection;
  const indexReadable = adviceIssue !== "index-missing" && adviceIssue !== "index-error";
  const selectionAvailable = !adviceLoading && indexReadable && selection.status === "ready";
  // What Hesapla may be asked for. A static build computes the plain plan of a published
  // combination and nothing else; with the service's capabilities in hand they are the
  // authority, switches and unpublished combinations included.
  const plainSelection =
    !selection.evidence.on && selection.top100.weight === 0 && selection.chip.chip === null;
  const computeAvailable =
    // A service on another capture would answer with a plan this page has to refuse.
    computeService !== "other-capture" &&
    !adviceLoading &&
    indexReadable &&
    (selection.computable
      ? selection.computable.selection
      : selection.status === "ready" && plainSelection && canComputeAdvice(request));
  const baselineAvailable =
    resolve(new URLSearchParams("mode=saf-puan&window=1")).status === "ready";
  const job = useAdviceJob(adviceClient, baselineAvailable);
  const requestKey = [
    adviceRequestKey(request),
    selection.status,
    selection.path,
    selection.top100.weight,
    selection.chip.chip ?? "",
  ].join(":");

  // A new selection starts clean: an earlier request's answer, wait or failure must not
  // read as this member's, strategy's, window's or rival's.
  // A wait this tab began for the same selection before a reload is picked up again.
  const { reset, resume } = job;
  const resumable = useRef(request);
  useEffect(() => {
    resumable.current = request;
  });
  useEffect(() => {
    reset();
    if (computeAvailable) resume?.(resumable.current);
  }, [requestKey, computeAvailable, reset, resume]);

  const current =
    (selectionAvailable || computeAvailable) &&
    job.state.phase !== "idle" &&
    sameAdviceRequest(job.state.request, request)
      ? job.state
      : null;
  // A computed plan is solved without the club's word, so it never stands in for the
  // switched-on plan, finished or while waiting.
  // The same holds for a Top 100 weight: the computed plan is the plain one.
  const evidenceOn = selection.evidence.on;
  // Nor for a chip the member chose: the computed plan plays none.
  // With the service's capabilities the request states its switches and the answer was
  // held to them, so a computed plan stands for exactly the selection that asked for it.
  const plainOnly = selection.computable
    ? selection.chip.chip === null
    : !evidenceOn && selection.top100.weight === 0 && selection.chip.chip === null;
  const finished = plainOnly && current?.phase === "done" ? current : null;
  const waiting = plainOnly && current?.phase === "waiting" ? current : null;
  let published: LeagueViewEnvelope<EntryAdvice> | null = null;
  // A computed answer is held to the squad on screen exactly as a published one is: a
  // plan solved from another capture is not shown beside this one's squad.
  const computedSnapshot = finished?.envelope.payload.source_snapshot_id;
  const computedElsewhere =
    // Only a build with a compute service holds its answers to the capture; a static
    // build has none to hold, and its injected clients answer as they always have.
    (computeService !== "static" || selection.computable !== undefined) &&
    finished != null &&
    computedSnapshot != null &&
    view.source_snapshot_id != null &&
    computedSnapshot !== view.source_snapshot_id;
  const computed = computedElsewhere ? null : finished;
  let rejectedContext = false;
  let rejectedUnreadable = false;
  if (advice && selectionAvailable) {
    try {
      const checked = checkedAdvice(advice, request);
      // The switched-on plan carries its evidence and the plain one does not. A document
      // that disagrees with the switch is not the plan the page is about to describe.
      if ((checked.payload.evidence !== undefined) !== selection.evidence.on) {
        throw new Error("The advice document does not match the manager's-word switch.");
      }
      // A weighted document names its weight, and the plain one names none.
      if ((checked.payload.top100?.weight ?? 0) !== selection.top100.weight) {
        throw new Error("The advice document does not match the Top 100 setting.");
      }
      // A chip document names the chip the member chose, twice: as the choice and as the
      // chip the plan plays. The plain one names none.
      const chosen = selection.chip.chip;
      if (
        (checked.payload.chip_choice?.chip ?? null) !== chosen ||
        (chosen !== null && checked.payload.chip !== chosen)
      ) {
        throw new Error("The advice document does not match the chosen chip.");
      }
      const snapshot = checked.payload.source_snapshot_id;
      rejectedContext =
        snapshot != null && view.source_snapshot_id != null && snapshot !== view.source_snapshot_id;
      published = rejectedContext ? null : checked;
    } catch (error) {
      rejectedContext = error instanceof AdviceContextError;
      rejectedUnreadable = !rejectedContext;
    }
  }
  rejectedContext = rejectedContext || computedElsewhere;
  // The panel must not announce a plan the card refuses to show.
  const panelJob: AdviceJob = computedElsewhere
    ? { ...job, state: { phase: "failed", request, reason: ANSWER_OTHER_CAPTURE } }
    : job;
  let shown: ShownAdvice | null = null;
  if (computed) {
    shown = {
      envelope: computed.envelope,
      origin: computed.source === "api-cache" ? "computed" : "published",
      source: computed.source,
    };
  } else if (published) {
    shown = { envelope: published, origin: waiting ? "published-while-computing" : "published" };
  } else if (waiting?.fallback) {
    shown = { envelope: waiting.fallback, origin: "baseline-while-computing" };
  }

  return {
    entryId,
    resolve,
    selection,
    indexReadable,
    selectionAvailable,
    computeAvailable,
    job: panelJob,
    request,
    shown,
    rejectedContext,
    rejectedUnreadable,
  };
}
