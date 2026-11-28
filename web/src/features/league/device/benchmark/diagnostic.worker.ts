/** Opt-in diagnostic build only. The app never imports this worker. */
import { highs } from "../lp/highs";
import { replyTo } from "../replies";
import type { DevicePlanRequest } from "../requests";
import { withinCeiling } from "../solve/ceiling";
import { kernel, probe } from "./kernel";
import type { LpSolver } from "../lp/problem";
import type { DevicePlanReply } from "../replies";
import { horizonProblem } from "../lp/horizon";
import { lpText } from "../lp/problem";
import { inSolverOrder } from "../solve/week";

const loaded = await highs();
self.postMessage({ kind: "loaded" });
self.onmessage = async (
  event: MessageEvent<
    | { kind: "probe"; count: number; warmup: number }
    | { kind: "solve"; request: DevicePlanRequest; audit?: boolean }
    | { kind: "fingerprint"; request: DevicePlanRequest }
  >,
) => {
  if (event.data.kind === "probe") {
    kernel(event.data.warmup);
    self.postMessage({ kind: "probe", ...probe(event.data.count) });
    return;
  }
  if (event.data.kind === "fingerprint") {
    const request = event.data.request;
    const text = lpText(
      horizonProblem(inSolverOrder(request.document), request.entry, request.window as 3 | 5),
    );
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    self.postMessage({
      kind: "model",
      sha256: Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join(
        "",
      ),
    });
    return;
  }
  // Only diagnostics get 300 seconds to distinguish a slow proof from a 60s refusal.
  // Production and ordinary regression ceilings remain unchanged.
  self.postMessage({ id: event.data.request.id, kind: "ready" });
  const clocked = withinCeiling(loaded, 300);
  if (!event.data.audit) {
    replyTo(clocked, event.data.request, (reply) => self.postMessage(reply));
    return;
  }
  let primary: string | undefined;
  const inspected: LpSolver = {
    remainingSeconds: clocked.remainingSeconds,
    solve(problem, options) {
      primary ??= problem;
      return clocked.solve(problem, options);
    },
  };
  const replies: DevicePlanReply[] = [];
  replyTo(inspected, event.data.request, (reply) => replies.push(reply));
  const bytes =
    primary === undefined
      ? null
      : await crypto.subtle.digest("SHA-256", new TextEncoder().encode(primary));
  self.postMessage({
    kind: "model",
    sha256:
      bytes === null
        ? null
        : Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join(""),
  });
  for (const reply of replies) self.postMessage(reply);
};
