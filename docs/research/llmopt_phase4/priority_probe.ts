/** Production bundle request, under the production cumulative worker ceiling. */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { solveRequest } from "../../../web/src/features/league/device/requests";
import { withinCeiling } from "../../../web/src/features/league/device/solve/ceiling";
import { DevicePlanRefused } from "../../../web/src/features/league/device/solve/week";

const require = createRequire(resolve("web/package.json"));
const native = await require("highs")({
  wasmBinary: readFileSync(require.resolve("highs/runtime")),
});
const rows = [];
for (const item of JSON.parse(readFileSync(0, "utf8"))) {
  const started = performance.now();
  let calls = 0;
  const statuses: string[] = [];
  const adapter: Parameters<typeof withinCeiling>[0] = {
    solve(lp, options) {
      calls++;
      const result = native.solve(lp, options);
      statuses.push(result.Status);
      return result;
    },
  };
  try {
    const main = solveRequest(withinCeiling(adapter), {
      ...item,
      preferenceBundle: undefined,
      priorityMain: true,
    });
    const answer = solveRequest(withinCeiling(adapter), {
      ...item,
      priorityReference: {
        squad: main.squad,
        startingXi: main.starting_xi,
        captain: main.captain,
        proved: !main.restricted,
      },
    });
    rows.push({
      id: item.id,
      status:
        main.restricted || answer.preference_bundle?.budget_exhausted
          ? "Feasible"
          : "Optimal",
      answer,
      calls,
      statuses,
      seconds: (performance.now() - started) / 1000,
    });
  } catch (error) {
    rows.push({
      id: item.id,
      status: error instanceof DevicePlanRefused ? error.status : "Error",
      error: String(error),
      calls,
      statuses,
      seconds: (performance.now() - started) / 1000,
    });
  }
}
process.stdout.write(JSON.stringify(rows));
