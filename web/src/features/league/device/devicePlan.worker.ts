/**
 * The device solve, off the page's thread. One message in (the two published documents),
 * one message out (the answer, or why there is none). The solver is loaded once per
 * worker and the wasm binary comes from the app's own assets, so nothing is fetched from
 * anywhere but the site.
 */

import loadHighs from "highs";
import wasmUrl from "highs/runtime?url";

import { DevicePlanRefused, solvePlan, type LpSolver } from "./planModel";
import type { DevicePlanAnswer, DevicePlanDocument, DevicePlanEntry } from "./types";

export interface DevicePlanRequest {
  id: number;
  document: DevicePlanDocument;
  entry: DevicePlanEntry;
}

export type DevicePlanReply =
  | { id: number; kind: "answer"; answer: DevicePlanAnswer }
  | { id: number; kind: "refused"; status: string; stage: string }
  | { id: number; kind: "failed" };

let solver: Promise<LpSolver> | null = null;

function highs(): Promise<LpSolver> {
  solver ??= loadHighs({ locateFile: () => wasmUrl }) as unknown as Promise<LpSolver>;
  return solver;
}

self.onmessage = async (event: MessageEvent<DevicePlanRequest>) => {
  const { id, document, entry } = event.data;
  let reply: DevicePlanReply;
  try {
    reply = { id, kind: "answer", answer: solvePlan(await highs(), document, entry) };
  } catch (error) {
    reply =
      error instanceof DevicePlanRefused
        ? { id, kind: "refused", status: error.status, stage: error.stage }
        : { id, kind: "failed" };
  }
  self.postMessage(reply);
};
