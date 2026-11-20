/** Dispatch the confirmed device hard-rule request against the installed production WASM. */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { checkedPreferences } from "../../../web/src/features/league/advice/decisionPreferences";
import { solveRequest } from "../../../web/src/features/league/device/requests";
import { deviceSelection } from "../../../web/src/features/league/device/selection";
import { withinCeiling } from "../../../web/src/features/league/device/solve/ceiling";
import { DevicePlanRefused } from "../../../web/src/features/league/device/solve/week";
import type { DevicePlanAnswer } from "../../../web/src/features/league/device/types";

const require = createRequire(resolve("web/package.json"));
const native = await require("highs")({
  wasmBinary: readFileSync(require.resolve("highs/runtime")),
});
const item = JSON.parse(readFileSync(0, "utf8"));
const preferences = checkedPreferences(item.preferences);
const selection = deviceSelection(
  { ...item.request, preferences, deviceAlternatives: true, deviceRun: true },
  { device_plan: item.entry },
  true,
);
const statuses: string[] = [];
const solver = withinCeiling({
  solve(problem, options) {
    const result = native.solve(problem, options);
    statuses.push(result.Status);
    return result;
  },
});
function compact(answer: DevicePlanAnswer) {
  return {
    in: [...answer.transfers_in].sort((a, b) => a - b),
    out: [...answer.transfers_out].sort((a, b) => a - b),
    squad: [...answer.squad].sort((a, b) => a - b),
    xi: [...answer.starting_xi].sort((a, b) => a - b),
    captain: answer.captain,
    chip: answer.chip,
    bank: answer.bank_after_tenths,
    hit: answer.transfer_hit_points,
    objective_scaled: answer.objective_scaled,
    published_net_scaled:
      (answer.expected_own_points - answer.transfer_hit_points) *
      item.document.rules.expected_points_scale,
  };
}
try {
  if (selection?.kind !== "plain")
    throw new Error("The request has no eligible device route");
  const answer = solveRequest(solver, {
    document: item.document,
    entry: item.entry,
    preferences,
    alternatives: true,
  });
  process.stdout.write(
    JSON.stringify({
      selection: selection.kind,
      status: statuses[0]?.toUpperCase() ?? "UNKNOWN",
      statuses,
      decision: compact(answer),
      alternatives: (answer.alternatives ?? []).map(compact),
    }),
  );
} catch (error) {
  const refused = error instanceof DevicePlanRefused;
  process.stdout.write(
    JSON.stringify({
      selection: selection?.kind ?? null,
      statuses,
      status:
        refused && error.status === "Infeasible" && error.stage === "plan"
          ? "INFEASIBLE"
          : "REFUSED",
      error: String(error),
      decision: null,
      alternatives: [],
    }),
  );
}
