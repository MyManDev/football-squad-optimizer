/**
 * A member's one-week plan solved on the member's own device.
 *
 * Offered for exactly the selection the publisher wrote inputs for: this member's plain
 * pure-points plan over one week, from the fifteen the page shows. The shared document
 * is read when the member asks, the solve runs in a worker, and the answer is shown as
 * the advice document the page already reads. A new selection starts clean.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { loadDevicePlan } from "../data";
import type { EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import type { AdviceRequest } from "../advice/adviceClient";
import { LeagueDataMissing } from "../dataErrors";
import { deviceAdviceEnvelope } from "./deviceAdvice";
import type { DevicePlanReply, DevicePlanRequest } from "./devicePlan.worker";
import { isDevicePlanEntry, type DevicePlanDocument, type DevicePlanEntry } from "./types";

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
  createSolver?: () => DeviceSolver;
  now?: () => Date;
}

function createWorker(): DeviceSolver {
  return new Worker(new URL("./devicePlan.worker.ts", import.meta.url), {
    type: "module",
  }) as unknown as DeviceSolver;
}

/** The one selection the published inputs describe: pure points, one week, nothing switched on. */
export function deviceSolvable(request: AdviceRequest): boolean {
  return (
    request.strategy === "saf-puan" &&
    request.window === 1 &&
    (request.rivalEntryId ?? null) === null &&
    (request.top100Weight ?? 0) === 0 &&
    !(request.managersWord ?? false) &&
    (request.chip ?? null) === null &&
    (request.model ?? "current") === "current" &&
    !request.preferences
  );
}

export function useDevicePlan(
  squad: EntrySquad,
  request: AdviceRequest,
  dependencies: DevicePlanDependencies = {},
): DevicePlan {
  const {
    loadDocument = loadDevicePlan,
    createSolver = createWorker,
    now = () => new Date(),
  } = dependencies;
  const entry: DevicePlanEntry | null = isDevicePlanEntry(squad.device_plan)
    ? squad.device_plan
    : null;
  const available = entry !== null && squad.source_snapshot_id !== null && deviceSolvable(request);
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
    if (!available || entry === null) return;
    const run = ++generation.current;
    const alive = () => generation.current === run;
    setState({ phase: "loading" });
    void (async () => {
      let document: DevicePlanDocument;
      try {
        const envelope = await loadDocument();
        document = envelope.payload;
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
          worker.postMessage({ id: run, document, entry });
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
  }, [available, entry, loadDocument, createSolver, now, setState, squad]);

  return { available, state, run, reset };
}
