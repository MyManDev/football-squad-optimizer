import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { solveWeek, inSolverOrder } from "../../../web/src/features/league/device/solve/week";
import type { LpSolver } from "../../../web/src/features/league/device/lp/problem";
const require = createRequire(resolve("web/package.json"));
const load = require("highs");
const native = await load({ wasmBinary: readFileSync(require.resolve("highs/runtime")) });
const solver: LpSolver = { solve: (lp, options) => native.solve(lp, { ...options, time_limit: 15 }) };
const cases = JSON.parse(readFileSync(0, "utf8"));
const results = [];
for (const item of cases) {
  const started = performance.now();
  try {
    const answer = solveWeek(solver, inSolverOrder(item.document), item.entry, { preferences: item.preferences });
    results.push({ id: item.id, status: answer ? "Optimal" : "Infeasible", answer, seconds: (performance.now()-started)/1000 });
  } catch (error) {
    results.push({ id: item.id, status: "Refused", error: String(error), seconds: (performance.now()-started)/1000 });
  }
}
process.stdout.write(JSON.stringify(results));

