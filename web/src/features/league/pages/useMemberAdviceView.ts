import { useCallback, useEffect, useMemo, useRef } from "react";

import { createAdviceClient, type AdviceRequest } from "../advice/adviceClient";
import { adviceRequestKey } from "../advice/adviceJobStore";
import { canComputeAdvice, resolvePublishedAdvice } from "../advice/adviceSelection";
import { AdviceContextError, checkedAdvice } from "../advice/adviceResponse";
import {
  ANSWER_OTHER_CAPTURE,
  sameAdviceRequest,
  useAdviceJob,
  type AdviceJob,
  type ComputePhase,
} from "../advice/useAdviceJob";
import { deviceComputable } from "../device/computable";
import { useDevicePlan, type DevicePlan } from "../device/useDevicePlan";

/** The same attempt, without the earlier answer it carried. */
function withoutEarlier(state: ComputePhase): ComputePhase {
  if (state.phase === "idle" || state.phase === "done") return state;
  return { ...state, earlier: null };
}
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
    deviceDependencies,
  }: LeagueMemberViewProps,
  searchParams: URLSearchParams,
) {
  const view = squad.payload;
  const adviceClient = useMemo(() => client ?? createAdviceClient(), [client]);
  const leagueId = view.league_id;
  const entryId = view.entry.entry_id;
  // What the member's own device can compute from this publish's inputs, stated beside
  // the service's capabilities so the controls offer it the same way.
  const onDevice = deviceComputable(view, members);
  const resolve = (params: URLSearchParams) =>
    resolvePublishedAdvice(
      params,
      leagueId,
      entryId,
      members,
      index,
      { season: view.season, gameweek: view.gameweek },
      capabilities,
      onDevice,
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
    (request.preferences?.keep_players.every((id) =>
      [...view.starting_xi, ...view.bench].some((p) => p.player_id === id),
    ) ??
      true) &&
    // A service on another capture would answer with a plan this page has to refuse.
    computeService !== "other-capture" &&
    !adviceLoading &&
    indexReadable &&
    (selection.computable
      ? selection.computable.selection
      : selection.status === "ready" && plainSelection && canComputeAdvice(request));
  const baselineAvailable =
    !request.preferences &&
    request.model !== "football" &&
    resolve(new URLSearchParams("mode=saf-puan&window=1")).status === "ready";
  const job = useAdviceJob(adviceClient, baselineAvailable, view.source_snapshot_id);
  // The chip the page shows is the selection's; without the service's capabilities the
  // request carries none, so the device is asked for the selection, chip included.
  const deviceRequest = { ...request, chip: request.chip ?? selection.chip.chip };
  const deviceJob = useDevicePlan(view, deviceRequest, deviceDependencies);
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
  const { reset, resume, readCached } = job;
  const readOnOpen = computeService === "ready" && computeAvailable && advice == null;
  const resumable = useRef(request);
  useEffect(() => {
    resumable.current = request;
  });
  const { reset: resetDevice, run: runOnDevice } = deviceJob;
  useEffect(() => {
    reset();
    resetDevice();
    if (computeAvailable) resume?.(resumable.current);
  }, [requestKey, computeAvailable, reset, resetDevice, resume]);
  useEffect(() => {
    if (readOnOpen) readCached?.(resumable.current);
  }, [requestKey, readOnOpen, readCached]);

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
  // With the service's capabilities the request states its switches and the answer was
  // held to them, so a computed plan stands for exactly the selection that asked for it.
  const plainOnly = selection.computable
    ? true
    : !evidenceOn && selection.top100.weight === 0 && selection.chip.chip === null;
  // The answer this same selection already received stays on the page while a later
  // attempt runs, and after one that fails or is refused: a second request that does not
  // succeed is not a reason to take the first answer away.
  const finished =
    plainOnly && current?.phase === "done"
      ? { envelope: current.envelope, source: current.source }
      : null;
  const earlier =
    plainOnly && current && current.phase !== "done" ? (current.earlier ?? null) : null;
  const waiting = plainOnly && current?.phase === "waiting" ? current : null;
  let published: LeagueViewEnvelope<EntryAdvice> | null = null;
  // A computed answer is held to the squad on screen exactly as a published one is: a
  // plan solved from another capture is not shown beside this one's squad.
  // Only a build with a compute service holds its answers to the capture; a static
  // build has none to hold, and its injected clients answer as they always have.
  const heldToCapture = computeService !== "static" || selection.computable !== undefined;
  const fromOtherCapture = (answer: { envelope: LeagueViewEnvelope<EntryAdvice> } | null) => {
    const snapshot = answer?.envelope.payload.source_snapshot_id;
    return (
      heldToCapture &&
      snapshot != null &&
      view.source_snapshot_id != null &&
      snapshot !== view.source_snapshot_id
    );
  };
  const computedElsewhere = fromOtherCapture(finished);
  // An earlier answer from another capture is dropped, not reported: the attempt that
  // is running is what the panel describes.
  const earlierKept = earlier !== null && !fromOtherCapture(earlier) ? earlier : null;
  const computed = computedElsewhere ? null : (finished ?? earlierKept);
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
      if (
        (checked.payload.chip_strategy?.top100_weight ??
          checked.payload.selection_top100_weight ??
          checked.payload.top100?.weight ??
          0) !== selection.top100.weight
      ) {
        throw new Error("The advice document does not match the Top 100 setting.");
      }
      // A chip document names the chip the member chose, twice: as the choice and as the
      // chip the plan plays. The plain one names none.
      const chosen = selection.chip.chip;
      if (
        (checked.payload.chip_strategy?.requested_chip ??
          checked.payload.chip_choice?.chip ??
          null) !== chosen ||
        (chosen !== null &&
          checked.payload.chip !== (checked.payload.chip_strategy?.selected_chip ?? chosen) &&
          !(chosen === "auto" && checked.payload.chip == null))
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
  // The panel must not announce a plan the card refuses to show, and it must not carry
  // an earlier selection's state for the one render before the reset lands.
  const panelJob: AdviceJob = computedElsewhere
    ? { ...job, state: { phase: "failed", request, reason: ANSWER_OTHER_CAPTURE } }
    : job.state.phase !== "idle" && !sameAdviceRequest(job.state.request, request)
      ? { ...job, state: { phase: "idle" } }
      : earlier !== null && earlierKept === null
        ? { ...job, state: withoutEarlier(job.state) }
        : job;
  // One answer at a time: asking the service drops the device's answer, and asking the
  // device drops the service's, so what the card shows is what was asked for last.
  const { reset: resetJob, compute: computeOnService } = job;
  const runOnDeviceAndDropJob = useCallback(() => {
    resetJob();
    runOnDevice();
  }, [resetJob, runOnDevice]);
  const device: DevicePlan = { ...deviceJob, run: runOnDeviceAndDropJob };
  const computeAndDropDevice = useCallback(
    (asked: AdviceRequest) => {
      resetDevice();
      computeOnService(asked);
    },
    [resetDevice, computeOnService],
  );
  const jobForPanel: AdviceJob = { ...panelJob, compute: computeAndDropDevice };
  let shown: ShownAdvice | null = null;
  if (computed) {
    shown = {
      envelope: computed.envelope,
      origin: computed.source === "api-cache" ? "computed" : "published",
      source: computed.source,
    };
  } else if (deviceJob.state.phase === "done") {
    // The device's state is keyed by the selection it answered, chip included.
    shown = { envelope: deviceJob.state.envelope, origin: "computed", source: "device" };
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
    job: jobForPanel,
    device,
    onDevice,
    request,
    shown,
    rejectedContext,
    rejectedUnreadable,
  };
}
