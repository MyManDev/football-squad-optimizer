/** The complete production one-week answer under one cumulative worker ceiling. */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { DevicePlanRefused, solvePlan } from "../../../web/src/features/league/device/solve/week";
import type { LpSolver } from "../../../web/src/features/league/device/lp/problem";

const require = createRequire(resolve("web/package.json"));
const load = require("highs");
const native = await load({ wasmBinary: readFileSync(require.resolve("highs/runtime")) });
const results = [];
for (const item of JSON.parse(readFileSync(0, "utf8"))) {
  const started = performance.now();
  let calls = 0;
  const statuses: string[] = [];
  const solver: LpSolver = {
    solve(lp, options) {
      const remaining = 120 - (performance.now() - started) / 1000;
      if (remaining <= 0) throw new Error("Cumulative device worker ceiling reached.");
      calls++;
      const result = native.solve(lp, { ...options, time_limit: remaining });
      statuses.push(result.Status);
      return result;
    },
  };
  try {
    const answer = solvePlan(solver, item.document, item.entry, () => performance.now(), item.chip,
      { preferences: item.preferences });
    results.push({ id: item.id, status: "Optimal", answer, calls, statuses,
      seconds: (performance.now() - started) / 1000 });
  } catch (error) {
    const infeasible = error instanceof DevicePlanRefused && error.status === "Infeasible"
      && error.stage === "plan";
    results.push({ id: item.id, status: infeasible ? "Infeasible" : "Refused", calls, statuses,
      error: String(error), seconds: (performance.now() - started) / 1000 });
  }
}
process.stdout.write(JSON.stringify(results));
