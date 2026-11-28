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
          const full = solveHorizon(
            withinCeiling(solver, 300),
            fixture.document as unknown as DevicePlanDocument,
            member.entry,
            window,
            undefined,
            "full",
          );
          const reference = member.reference[String(window) as "3" | "5"];
          expect(answer.objective_scaled).toBe(reference.objective_scaled);
          expect(Math.abs(answer.objective - reference.objective)).toBeLessThanOrEqual(1e-6);
          expect(answer.objective_scaled).toBe(full.objective_scaled);
          expect(Math.abs(answer.objective - full.objective)).toBeLessThanOrEqual(1e-6);
          const rank = new Map(fixture.document.players.map((player, index) => [player.id, index]));
          const tiers = (weeks: typeof answer.plan_weeks) => [
            weeks.reduce((sum, week) => sum + rank.get(week.captain)!, 0),
            weeks.reduce(
              (sum, week) => sum + week.starting_xi.reduce((s, id) => s + rank.get(id)!, 0),
              0,
            ),
            weeks.reduce(
              (sum, week) => sum + week.squad.reduce((s, id) => s + rank.get(id)!, 0),
              0,
            ),
          ];
          expect(tiers(answer.plan_weeks)).toEqual(tiers(full.plan_weeks));
          if ((reference as { unique_moves?: boolean | null }).unique_moves === true)
            for (const [w, week] of answer.plan_weeks.entries()) {
              expect(week.transfers_in).toEqual(full.plan_weeks[w]!.transfers_in);
              expect(week.transfers_out).toEqual(full.plan_weeks[w]!.transfers_out);
              expect(week.transfers_in).toEqual(reference.weeks[w]!.transfers_in);
              expect(week.transfers_out).toEqual(reference.weeks[w]!.transfers_out);
            }
          // Two independent diagnostic300 solves, without changing either production ceiling.
        }, 630_000);
  },
);
