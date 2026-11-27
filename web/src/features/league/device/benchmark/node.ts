/** Built separately for an opt-in Node run, never imported by the app. */
import loadHighs from "highs";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { replyTo } from "../replies";
import type { DevicePlanRequest } from "../requests";
import type { LpSolver } from "../lp/problem";
import { withinCeiling } from "../solve/ceiling";
import { horizonProblem } from "../lp/horizon";
import { lpText } from "../lp/problem";
import { inSolverOrder } from "../solve/week";

export function modelFingerprint(request: DevicePlanRequest) {
  return createHash("sha256")
    .update(
      lpText(
        horizonProblem(inSolverOrder(request.document), request.entry, request.window as 3 | 5),
      ),
    )
    .digest("hex");
}

export async function nodeSolver() {
  const require = createRequire(import.meta.url);
  const solver = (await loadHighs({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
  return (request: DevicePlanRequest) => {
    const started = performance.now();
    let reply: unknown;
    replyTo(withinCeiling(solver, 300), request, (value) => {
      reply = value;
    });
    return { reply, elapsed_seconds: (performance.now() - started) / 1000 };
  };
}
