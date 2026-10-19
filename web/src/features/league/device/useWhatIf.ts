/**
 * The what-if mode's state (#1132): the fifteen the member is trying, starting from the
 * advised one, with its account read at once on the page and its points read by the
 * device's solver in a worker. The capture's table is read when the member starts, held
 * to the capture on screen, and kept: from then on every change is answered on the
 * device, with no network. Until a change's points arrive the last ones stay, marked as
 * being read, so no number is shown that the solver did not give.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { LeagueDataMissing } from "../dataErrors";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { useLeague } from "../useLeague";
import { isDevicePlanEntry, type DevicePlanDocument, type DevicePlanEntry } from "./types";
import type { WhatIfReply, WhatIfRequest } from "./whatIf.worker";
import { whatIfAccount, whatIfDocument, type WhatIfAccount } from "./whatIf";

/** A worker-shaped solver: the real worker, or a test double answering in process. */
export interface WhatIfSolver {
  postMessage(request: WhatIfRequest): void;
  onmessage: ((event: MessageEvent<WhatIfReply>) => void) | null;
  onerror?: ((event: unknown) => void) | null;
  terminate(): void;
}

export interface WhatIfDependencies {
  /** Reads the capture's table; the signal ends the read when the page leaves. */
  loadDocument?: (signal: AbortSignal) => Promise<LeagueViewEnvelope<DevicePlanDocument>>;
  createSolver?: () => WhatIfSolver;
}

/**
 * Where the mode stands: `failed` is a table that could not be read, `solver-failed` a
 * solver that could not read a fifteen. From any phase but `loading` and `ready` the member
 * can start again.
 */
export type WhatIfPhase =
  "idle" | "loading" | "ready" | "other-capture" | "unpublished" | "failed" | "solver-failed";

export interface WhatIf {
  phase: WhatIfPhase;
  /** The capture's table in solver order, once read. */
  document: DevicePlanDocument | null;
  squad: readonly number[];
  account: WhatIfAccount | null;
  /** The advised fifteen's account, so the difference is taken net of both hits. */
  advisedAccount: WhatIfAccount | null;
  /** The advised fifteen's points and the tried one's; null until the solver answers. */
  points: { advised: number | null; tried: number | null } | null;
  /** Whether the points shown are for an earlier fifteen while this one's are read. */
  reading: boolean;
  start: () => void;
  remove: (playerId: number) => void;
  add: (playerId: number) => void;
  reset: () => void;
}

function createWorker(): WhatIfSolver {
  return new Worker(new URL("./whatIf.worker.ts", import.meta.url), {
    type: "module",
  }) as unknown as WhatIfSolver;
}

/**
 * `advised` is the plan's fifteen the mode starts from and returns to; the member's block
 * on their entry document (`device_plan`) gives the bank, the free transfers and the
 * sale prices, exactly as the device solve reads them.
 */
export function useWhatIf(
  squad: EntrySquad,
  advised: readonly number[],
  dependencies: WhatIfDependencies = {},
): WhatIf {
  const { tree } = useLeague();
  const {
    loadDocument = (signal: AbortSignal) => tree.devicePlan(squad.source_snapshot_id, { signal }),
    createSolver = createWorker,
  } = dependencies;
  const entry: DevicePlanEntry | null = isDevicePlanEntry(squad.device_plan)
    ? squad.device_plan
    : null;
  // The advised fifteen by its players, so a new array with the same players is the same
  // advice and asks nothing again.
  const advisedKey = advised.join(",");
  const advisedIds = useMemo(
    () => (advisedKey === "" ? [] : advisedKey.split(",").map(Number)),
    [advisedKey],
  );
  const [phase, setPhase] = useState<WhatIfPhase>("idle");
  const [document, setDocument] = useState<DevicePlanDocument | null>(null);
  // The tried fifteen, keyed by the advice it started from: new advice starts it again.
  const [tried, setTried] = useState<{ key: string; squad: readonly number[] } | null>(null);
  const current = tried?.key === advisedKey ? tried.squad : advisedIds;
  const [answer, setAnswer] = useState<{
    squad: readonly number[];
    advised: number | null;
    tried: number | null;
  } | null>(null);
  const solver = useRef<WhatIfSolver | null>(null);
  const asked = useRef(0);
  // The read in flight, ended when the page leaves so nothing is created after it.
  const reading = useRef<AbortController | null>(null);

  /** The worker is ended on a solver failure, so the next start creates a fresh one. */
  const solverFailed = useCallback(() => {
    solver.current?.terminate();
    solver.current = null;
    setDocument(null);
    setPhase("solver-failed");
  }, []);

  const start = useCallback(() => {
    if (entry === null || phase === "loading" || phase === "ready") return;
    setPhase("loading");
    reading.current?.abort();
    const read = new AbortController();
    reading.current = read;
    loadDocument(read.signal).then(
      (envelope) => {
        if (read.signal.aborted) return;
        const table = whatIfDocument(envelope.payload);
        const known = new Set(table.players.map((player) => player.id));
        // The table is held to the capture on screen, and must carry the advised fifteen.
        if (
          table.source_snapshot_id !== squad.source_snapshot_id ||
          !advisedIds.every((id) => known.has(id))
        ) {
          setPhase("other-capture");
          return;
        }
        // A worker that cannot be created answers as a failure, as the device's does.
        try {
          solver.current ??= createSolver();
        } catch {
          solverFailed();
          return;
        }
        solver.current.onerror = solverFailed;
        setDocument(table);
        setPhase("ready");
      },
      (error: unknown) => {
        if (read.signal.aborted) return;
        setPhase(error instanceof LeagueDataMissing ? "unpublished" : "failed");
      },
    );
  }, [
    entry,
    phase,
    loadDocument,
    createSolver,
    solverFailed,
    squad.source_snapshot_id,
    advisedIds,
  ]);

  // Each fifteen tried asks the worker for its points beside the advised one's; only the
  // last question's answer is kept.
  useEffect(() => {
    const worker = solver.current;
    if (document === null || worker === null) return;
    const id = ++asked.current;
    worker.onmessage = (event) => {
      const reply = event.data;
      if (reply.id !== asked.current) return;
      if (reply.kind === "failed") {
        solverFailed();
        return;
      }
      setAnswer({
        squad: current,
        advised: reply.values[0] ?? null,
        tried: reply.values[1] ?? null,
      });
    };
    worker.postMessage({ id, document, squads: [[...advisedIds], [...current]] });
  }, [document, advisedIds, current, solverFailed]);

  // An unmounted page keeps no worker.
  useEffect(
    () => () => {
      reading.current?.abort();
      solver.current?.terminate();
      solver.current = null;
    },
    [],
  );

  const account = useMemo(
    () => (document && entry ? whatIfAccount(document, entry, current) : null),
    [document, entry, current],
  );
  const advisedAccount = useMemo(
    () => (document && entry ? whatIfAccount(document, entry, advisedIds) : null),
    [document, entry, advisedIds],
  );
  const remove = useCallback(
    (playerId: number) =>
      setTried({ key: advisedKey, squad: current.filter((id) => id !== playerId) }),
    [advisedKey, current],
  );
  const add = useCallback(
    (playerId: number) => {
      if (current.includes(playerId)) return;
      setTried({ key: advisedKey, squad: [...current, playerId] });
    },
    [advisedKey, current],
  );
  const reset = useCallback(() => setTried(null), []);

  return {
    phase: entry === null ? "unpublished" : phase,
    document,
    squad: current,
    account,
    advisedAccount,
    points: answer ? { advised: answer.advised, tried: answer.tried } : null,
    reading: phase === "ready" && answer?.squad !== current,
    start,
    remove,
    add,
    reset,
  };
}
