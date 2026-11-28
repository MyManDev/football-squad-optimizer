/** Opt-in complete-pool parity after tightening, using the unchanged server references. */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { beforeAll, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/horizons-scale.json";
import type { LpSolver } from "./lp/problem";
import { withinCeiling } from "./solve/ceiling";
import { solveHorizon } from "./solve/horizon";
import type { DevicePlanDocument } from "./types";

describe.skipIf(process.env.SQUADOPT_DEVICE_SCALE_PARITY !== "1")(
  "600-player full-pool parity",
  () => {
    let solver: LpSolver;
    beforeAll(async () => {
      const require = createRequire(import.meta.url);
      const load = (await import("highs")).default;
      solver = (await load({
        wasmBinary: readFileSync(require.resolve("highs/runtime")),
      })) as unknown as LpSolver;
    }, 60_000);

    for (const member of fixture.members)
      for (const window of [3, 5] as const)
        it(`FT${member.entry.free_transfers}, H${window}`, () => {
          expect(fixture.document.players).toHaveLength(600);
          const answer = solveHorizon(
            withinCeiling(solver, 300),
            fixture.document as unknown as DevicePlanDocument,
            member.entry,
            window,
          );
          const reference = member.reference[String(window) as "3" | "5"];
          expect(answer.objective_scaled).toBe(reference.objective_scaled);
          expect(Math.abs(answer.objective - reference.objective)).toBeLessThanOrEqual(1e-6);
        }, 315_000);
  },
);
