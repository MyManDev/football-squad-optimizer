/**
 * A member's one-week plan solved on the member's own device.
 *
 * Offered for the selections the published inputs describe (`selection.ts`): this
 * member's plain pure-points plan over one week, from the fifteen the page shows, with a
 * chip the member still holds played that week, or a rival strategy against a named rival
 * whose entry document gives their eleven. The shared document (and the rival's) is read
 * when the member asks, the solve runs in a worker, and the answer is shown as the advice
 * document the page already reads. A new selection starts clean.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useLeague } from "../useLeague";
import type { EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import type { AdviceRequest } from "../advice/adviceClient";
import { LeagueDataMissing } from "../dataErrors";
import { deviceAdviceEnvelope } from "./deviceAdvice";
import type { DevicePlanReply, DevicePlanRequest } from "./deviceSolver.worker";
import { deviceSelection, rivalFromSquad } from "./selection";
import { isDevicePlanEntry, type DevicePlanDocument, type DevicePlanEntry } from "./types";

export { deviceChip, deviceSelection } from "./selection";

export type DevicePlanPhase =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "solving" }
  | { phase: "done"; envelope: LeagueViewEnvelope<EntryAdvice>; seconds: number }
  | { phase: "refused"; status: string }
  | { phase: "other-capture" }
  | { phase: "unpublished" }
  | { phase: "failed" };

export interface DevicePlan {
  /** Whether this selection is one the device can solve from the published inputs. */
  available: boolean;
  state: DevicePlanPhase;
  run: () => void;
  reset: () => void;
}

/** A worker-shaped solver: the real worker, or a test double answering in process. */
export interface DeviceSolver {
  postMessage(request: DevicePlanRequest): void;
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null;
  /** A worker that could not load or evaluate reports here; the page treats it as failed. */
  onerror?: ((event: unknown) => void) | null;
  terminate(): void;
}

export interface DevicePlanDependencies {
  loadDocument?: () => Promise<LeagueViewEnvelope<DevicePlanDocument>>;
  /** The rival's entry document, for a rival strategy. */
  loadRival?: (entryId: number) => Promise<LeagueViewEnvelope<EntrySquad>>;
  createSolver?: () => DeviceSolver;
  now?: () => Date;
}

function createWorker(): DeviceSolver {
  // The worker's file name is part of what the browser caches; renaming it changes its URL.
  return new Worker(new URL("./deviceSolver.worker.ts", import.meta.url), {
    type: "module",
  }) as unknown as DeviceSolver;
}

/** Whether this request is one the device solves from the published inputs. */
export function deviceSolvable(request: AdviceRequest, squad: Pick<EntrySquad, "chips">): boolean {
  return deviceSelection(request, squad) !== null;
}

export function useDevicePlan(
  squad: EntrySquad,
  request: AdviceRequest,
  dependencies: DevicePlanDependencies = {},
): DevicePlan {
  const { tree } = useLeague();
  const {
    loadDocument = () => tree.devicePlan(),
    loadRival = (entryId: number) => tree.entrySquad(entryId),
    createSolver = createWorker,
    now = () => new Date(),
  } = dependencies;
  const entry: DevicePlanEntry | null = isDevicePlanEntry(squad.device_plan)
    ? squad.device_plan
    : null;
  const selection = deviceSelection(request, squad);
  const available = entry !== null && squad.source_snapshot_id !== null && selection !== null;
  // The state is keyed by the selection it was asked for: a new selection reads idle
  // without an effect, and a late reply for the old one is ignored by its generation.
  const [held, setHeld] = useState<{ key: string; state: DevicePlanPhase }>({
    key: "",
    state: { phase: "idle" },
  });
  const solver = useRef<DeviceSolver | null>(null);
  const generation = useRef(0);
  const requestKey = JSON.stringify([
    squad.source_snapshot_id,
    request.leagueId,
    request.entryId,
    request.season ?? null,
    request.gameweek ?? null,
    squad.entry.entry_id,
    request.strategy,
    request.window,
    request.rivalEntryId ?? null,
    request.top100Weight ?? 0,
    request.managersWord ?? false,
    request.chip ?? null,
    request.model ?? "current",
  ]);

  const state: DevicePlanPhase = held.key === requestKey ? held.state : { phase: "idle" };
  const setState = useCallback(
    (next: DevicePlanPhase) => setHeld({ key: requestKey, state: next }),
    [requestKey],
  );
  const reset = useCallback(() => {
    generation.current += 1;
    setState({ phase: "idle" });
  }, [setState]);

  // An unmounted page keeps no worker.
  useEffect(
    () => () => {
      solver.current?.terminate();
      solver.current = null;
    },
    [],
  );

  const run = useCallback(() => {
    if (!available || entry === null || selection === null) return;
    const run = ++generation.current;
    const alive = () => generation.current === run;
    setState({ phase: "loading" });
    void (async () => {
      let document: DevicePlanDocument;
      let strategy: DevicePlanRequest["strategy"] = null;
      try {
        const envelope = await loadDocument();
        document = envelope.payload;
        if (selection.kind === "rival") {
          // The rival's eleven comes from their own entry document, held to the same
          // capture as the member's; a document naming no captain cannot be scored.
          let rivalSquad: EntrySquad;
          try {
            rivalSquad = (await loadRival(selection.rivalEntryId)).payload;
          } catch {
            // The rival's document, not the device inputs, is what is missing.
            if (alive()) setState({ phase: "failed" });
            return;
          }
          if (rivalSquad.source_snapshot_id !== squad.source_snapshot_id) {
            if (alive()) setState({ phase: "other-capture" });
            return;
          }
          const rival = rivalFromSquad(selection.rivalEntryId, rivalSquad);
          if (rival === null) {
            if (alive()) setState({ phase: "refused", status: "rival captain unknown" });
            return;
          }
          strategy = { name: selection.strategy, rival };
        }
      } catch (error) {
        if (alive()) {
          setState({ phase: error instanceof LeagueDataMissing ? "unpublished" : "failed" });
        }
        return;
      }
      if (!alive()) return;
      // The inputs are held to the capture on screen exactly as a published plan is.
      if (document.source_snapshot_id !== squad.source_snapshot_id) {
        setState({ phase: "other-capture" });
        return;
      }
      const chip = selection.kind === "chip" ? selection.chip : null;
      // A worker that cannot be created, load or evaluate answers as a failure, and the
      // next press creates a fresh one rather than reusing a dead worker.
      let worker: DeviceSolver;
      try {
        solver.current ??= createSolver();
        worker = solver.current;
      } catch {
        setState({ phase: "failed" });
        return;
      }
      const reply = await new Promise<DevicePlanReply | null>((resolve) => {
        worker.onmessage = (event) => {
          if (event.data.id !== run) return;
          if (event.data.kind === "ready") {
            if (alive()) setState({ phase: "solving" });
            return;
          }
          resolve(event.data);
        };
        worker.onerror = () => {
          solver.current?.terminate();
          solver.current = null;
          resolve(null);
        };
        try {
          worker.postMessage({
            id: run,
            document,
            entry,
            chip,
            strategy,
            top100Weight: selection.kind === "top100" ? selection.weight : 0,
          });
        } catch {
          resolve(null);
        }
      });
      if (!alive()) return;
      if (reply === null || reply.kind === "failed" || reply.kind === "ready") {
        setState({ phase: "failed" });
      } else if (reply.kind === "refused") {
        setState({ phase: "refused", status: reply.status });
      } else {
        setState({
          phase: "done",
          envelope: deviceAdviceEnvelope(document, squad, reply.answer, now()),
          seconds: reply.answer.seconds,
        });
      }
    })();
  }, [available, entry, selection, loadDocument, loadRival, createSolver, now, setState, squad]);

  return { available, state, run, reset };
}
