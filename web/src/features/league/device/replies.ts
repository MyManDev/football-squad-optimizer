/**
 * What the worker posts for one request once its solver has loaded: the answer, or why
 * there is none. A request for chip gains is answered twice, so the plan is not held back
 * by the chips: the plain plan as soon as it is solved (`plan`), with its own solving
 * time, then each held chip's gain against it (`gains`). Both come from the one run, so
 * the plain plan is solved once and every solve shares the run's one ceiling. A failure
 * after the plan was posted loses the gains, never the plan.
 */

import type { LpSolver } from "./lp/problem";
import { solveRequest, type DevicePlanRequest } from "./requests";
import { DevicePlanRefused } from "./solve/week";
import type { DeviceChip, DevicePlanAnswer } from "./types";

export type DevicePlanReply =
  | { id: number; kind: "ready" }
  | { id: number; kind: "answer"; answer: DevicePlanAnswer }
  | { id: number; kind: "plan"; answer: DevicePlanAnswer }
  | {
      id: number;
      kind: "gains";
      /** Each held chip's gain, null where its solve was refused; null where the run failed. */
      gains: Partial<Record<DeviceChip, number | null>> | null;
      /** The whole run's solving time: the plain plan and every chip. */
      seconds: number;
    }
  | { id: number; kind: "refused"; status: string; stage: string }
  | { id: number; kind: "failed" };

export function replyTo(
  solver: LpSolver,
  request: DevicePlanRequest,
  post: (reply: DevicePlanReply) => void,
  now: () => number = () => performance.now(),
): void {
  const { id } = request;
  const started = now();
  let planned = false;
  const onPlan = (answer: DevicePlanAnswer) => {
    planned = true;
    post({ id, kind: "plan", answer });
  };
  let reply: DevicePlanReply;
  try {
    const answer = solveRequest(solver, request, now, onPlan);
    reply = planned
      ? { id, kind: "gains", gains: answer.chip_gains ?? {}, seconds: answer.seconds }
      : { id, kind: "answer", answer };
  } catch (error) {
    reply = planned
      ? { id, kind: "gains", gains: null, seconds: (now() - started) / 1000 }
      : error instanceof DevicePlanRefused
        ? { id, kind: "refused", status: error.status, stage: error.stage }
        : { id, kind: "failed" };
  }
  post(reply);
}
