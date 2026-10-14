/**
 * A member's one-week plan solved on the member's own device.
 *
 * Offered for the selections the published inputs describe (`selection.ts`): this
 * member's plain pure-points plan over one week, from the fifteen the page shows, with a
 * chip the member still holds played that week, a rival strategy against a named rival
 * whose entry document gives their eleven, or a Top 100 weight the member block names. The shared document (and the rival's) is read
 * when the member asks, the solve runs in a worker, and the answer is shown as the advice
 * document the page already reads. A new selection starts clean, and a reset or a new
 * selection stops a solve still running: its worker is ended, not left computing an
 * answer nobody will read. A worker that does not answer within the solve's ceiling, and
 * a grace beyond it, is ended too and the run fails. Each run leaves User Timing marks and
 * measures of its stages (`DeviceTimeline`); the device spec prints the measures.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useLeague } from "../useLeague";
import type { EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import type { AdviceRequest } from "../advice/adviceClient";
import { LeagueDataMissing } from "../dataErrors";
import { deviceAdviceEnvelope } from "./deviceAdvice";
import {
  DEVICE_LOAD_ALLOWANCE_SECONDS,
  DEVICE_REPLY_GRACE_SECONDS,
  DEVICE_SOLVE_CEILING_SECONDS,
} from "./solve/ceiling";
import type { DevicePlanReply, DevicePlanRequest } from "./deviceSolver.worker";
import { deviceSelection, offeredDeviceSelection, rivalFromSquad } from "./selection";
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

/**
 * Whether the device's last run ended without a plan: it failed, refused the selection,
 * found inputs from another capture or found none. The page then stops offering the
 * device as the way to this selection and says what it would say without it.
 */
export function deviceEndedWithoutPlan(state: DevicePlanPhase): boolean {
  return (
    state.phase === "failed" ||
    state.phase === "refused" ||
    state.phase === "other-capture" ||
    state.phase === "unpublished"
  );
}

export interface DevicePlan {
  /** Whether this selection is one the device can solve from the published inputs. */
  available: boolean;
  state: DevicePlanPhase;
  /** Starts a run; while this selection's run is loading or solving, it starts nothing. */
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
  /** Timers, for tests; the page's own otherwise. */
  setTimer?: (callback: () => void, milliseconds: number) => unknown;
  clearTimer?: (handle: unknown) => void;
  /** Where a run leaves its marks and measures, for tests; the page's own otherwise. */
  timeline?: DeviceTimeline;
}

/**
 * User Timing, as a run writes it. A run marks the press, its inputs read, its request
 * posted, the worker ready and the reply (`answer`, `refused` or `failed`), each mark
 * named for the run (`device:<n>:press`), and measures `device:inputs` (press to inputs),
 * `device:load` (posted to ready) and `device:solve` (ready to reply) between its own marks.
 */
export interface DeviceTimeline {
  mark(name: string): void;
  /** A measure from the mark named `start` to the mark named `end`. */
  measure(name: string, start: string, end: string): void;
}

// Module-level, so the hook's callbacks keep one identity from render to render.
function startTimer(callback: () => void, milliseconds: number): unknown {
  return setTimeout(callback, milliseconds);
}

function stopTimer(handle: unknown): void {
  clearTimeout(handle as ReturnType<typeof setTimeout>);
}

// The page's own User Timing; a browser without it keeps no marks.
const pageTimeline: DeviceTimeline = {
  mark(name) {
    globalThis.performance?.mark?.(name);
  },
  measure(name, start, end) {
    globalThis.performance?.measure?.(name, start, end);
  },
};

// Runs are numbered across the page, not by a hook's generation, so a page that mounts
// the hook again never names two runs' marks alike.
let runsMarked = 0;

/** A new run's marks and measures. A timeline that throws loses that write, never the run. */
function runTimeline(timeline: DeviceTimeline) {
  const run = ++runsMarked;
  const named = (point: string) => `device:${run}:${point}`;
  const quietly = (write: () => void) => {
    try {
      write();
    } catch {
      // The run goes on unmarked.
    }
  };
  return {
    mark: (point: string) => quietly(() => timeline.mark(named(point))),
    measure: (name: string, from: string, to: string) =>
      quietly(() => timeline.measure(`device:${name}`, named(from), named(to))),
  };
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
  /**
   * The rivals the device's statement offers (`computable.ts`): a rival strategy against
   * anyone else is not offered, because the device could not play it. Absent, any rival.
   */
  rivals?: readonly number[],
): DevicePlan {
  const { tree } = useLeague();
  const {
    loadDocument = () => tree.devicePlan(squad.source_snapshot_id),
    loadRival = (entryId: number) => tree.entrySquad(entryId),
    createSolver = createWorker,
    now = () => new Date(),
    setTimer = startTimer,
    clearTimer = stopTimer,
    timeline = pageTimeline,
  } = dependencies;
  const entry: DevicePlanEntry | null = isDevicePlanEntry(squad.device_plan)
    ? squad.device_plan
    : null;
  const selection = offeredDeviceSelection(request, squad, rivals);
  const available = entry !== null && squad.source_snapshot_id !== null && selection !== null;
  // The state is keyed by the selection it was asked for: a new selection reads idle
  // without an effect, and a late reply for the old one is ignored by its generation.
  const [held, setHeld] = useState<{ key: string; state: DevicePlanPhase }>({
    key: "",
    state: { phase: "idle" },
  });
  const solver = useRef<DeviceSolver | null>(null);
  const generation = useRef(0);
  // The run a worker is solving now: how to end its wait, and its watchdog.
  const pending = useRef<{
    settle: (reply: DevicePlanReply | null) => void;
    timer: unknown;
  } | null>(null);
  // The run still loading or solving, by its generation. A run asked for meanwhile starts
  // nothing: it reads no inputs and posts no message. A reset or a new selection moves the
  // generation on, so the run after it starts at once.
  const inFlight = useRef<number | null>(null);
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
  /** End a solve still running: its worker is terminated and its wait settles empty. */
  const stopSolving = useCallback(() => {
    const running = pending.current;
    if (running === null) return;
    pending.current = null;
    clearTimer(running.timer);
    solver.current?.terminate();
    solver.current = null;
    running.settle(null);
  }, [clearTimer]);

  const reset = useCallback(() => {
    generation.current += 1;
    stopSolving();
    setState({ phase: "idle" });
  }, [setState, stopSolving]);

  // The effects below follow the selection and the page's life, not the caller's timers:
  // they read the latest stop through a ref, so timers passed inline do not re-run them.
  const stop = useRef(stopSolving);
  useEffect(() => {
    stop.current = stopSolving;
  }, [stopSolving]);

  // Leaving a selection stops its run, as a reset does: its worker is ended, and a run it
  // leaves loading or solving reads idle, so a return to that selection finds no busy
  // phase that nothing will finish. This is the old selection's cleanup, so it runs before
  // any effect of the new one, and a run started there is not the one stopped.
  useEffect(
    () => () => {
      generation.current += 1;
      stop.current();
      setHeld((last) =>
        last.state.phase === "loading" || last.state.phase === "solving"
          ? { key: last.key, state: { phase: "idle" } }
          : last,
      );
    },
    [requestKey],
  );

  // An unmounted page keeps no worker.
  useEffect(
    () => () => {
      stop.current();
      solver.current?.terminate();
      solver.current = null;
    },
    [],
  );

  const run = useCallback(() => {
    if (!available || entry === null || selection === null) return;
    if (inFlight.current === generation.current) return;
    const run = ++generation.current;
    inFlight.current = run;
    const alive = () => generation.current === run;
    const timing = runTimeline(timeline);
    timing.mark("press");
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
      timing.mark("inputs");
      timing.measure("inputs", "press", "inputs");
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
      // Whether the worker said it was ready: only then is there a solve to measure.
      let ready = false;
      const reply = await new Promise<DevicePlanReply | null>((resolve) => {
        // A worker that never answers is ended: the load gets its allowance, and the
        // solves their ceiling, each with a grace beyond it.
        const watch = (seconds: number) =>
          setTimer(
            () => {
              if (pending.current?.settle === settle) stopSolving();
            },
            (seconds + DEVICE_REPLY_GRACE_SECONDS) * 1000,
          );
        const settle = (value: DevicePlanReply | null) => {
          if (pending.current?.settle === settle) {
            clearTimer(pending.current.timer);
            pending.current = null;
          }
          resolve(value);
        };
        pending.current = { settle, timer: watch(DEVICE_LOAD_ALLOWANCE_SECONDS) };
        worker.onmessage = (event) => {
          if (event.data.id !== run) return;
          if (event.data.kind === "ready") {
            ready = true;
            timing.mark("ready");
            timing.measure("load", "posted", "ready");
            if (pending.current?.settle === settle) {
              clearTimer(pending.current.timer);
              pending.current.timer = watch(DEVICE_SOLVE_CEILING_SECONDS);
            }
            if (alive()) setState({ phase: "solving" });
            return;
          }
          settle(event.data);
        };
        worker.onerror = () => {
          solver.current?.terminate();
          solver.current = null;
          settle(null);
        };
        timing.mark("posted");
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
          settle(null);
        }
      });
      if (!alive()) return;
      const ending = reply === null || reply.kind === "ready" ? "failed" : reply.kind;
      timing.mark(ending);
      if (ready) timing.measure("solve", "ready", ending);
      if (reply === null || reply.kind === "failed" || reply.kind === "ready") {
        setState({ phase: "failed" });
      } else if (reply.kind === "refused") {
        setState({ phase: "refused", status: reply.status });
      } else {
        setState({
          phase: "done",
          envelope: deviceAdviceEnvelope(
            document,
            squad,
            reply.answer,
            now(),
            tree.league.leagueId,
          ),
          seconds: reply.answer.seconds,
        });
      }
    })().finally(() => {
      if (inFlight.current === run) inFlight.current = null;
    });
  }, [
    available,
    entry,
    selection,
    loadDocument,
    loadRival,
    createSolver,
    now,
    setState,
    squad,
    setTimer,
    clearTimer,
    timeline,
    stopSolving,
    tree.league.leagueId,
  ]);

  return { available, state, run, reset };
}
