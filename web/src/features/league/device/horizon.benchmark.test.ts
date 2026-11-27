/** Explicit opt-in timing runs; ordinary correctness gates do not publish machine timings. */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import small from "../../../fixtures/device-plan/horizons.json";
import scale from "../../../fixtures/device-plan/horizons-scale.json";
import type { LpSolver } from "./lp/problem";
import { DEVICE_HORIZON_SOLVE_CEILING_SECONDS, withinCeiling } from "./solve/ceiling";
import { solveHorizon } from "./solve/horizon";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";

interface Dataset {
  document: DevicePlanDocument;
  members: Array<{
    entry_id: number;
    entry: DevicePlanEntry;
    reference?: Record<string, { objective: number; objective_scaled: number }>;
  }>;
}

const datasets = [
  { pool: "parity-24", fixture: small as unknown as Dataset },
  { pool: "synthetic-600", fixture: scale as unknown as Dataset },
];
const repeats = 3;
const samples: Array<{ pool: string; member: number; window: number; seconds: number }> = [];
const require = createRequire(import.meta.url);
let highs: LpSolver;

function summary(values: number[]) {
  const ordered = [...values].sort((a, b) => a - b);
  const middle = Math.floor(ordered.length / 2);
  return {
    count: ordered.length,
    median: ordered.length % 2 ? ordered[middle] : (ordered[middle - 1]! + ordered[middle]!) / 2,
    maximum: ordered.at(-1),
  };
}

describe.skipIf(process.env.SQUADOPT_DEVICE_BENCHMARK !== "1")("horizon Node benchmark", () => {
  beforeAll(async () => {
    const load = (await import("highs")).default;
    highs = (await load({
      wasmBinary: readFileSync(require.resolve("highs/runtime")),
    })) as unknown as LpSolver;
  }, 60_000);

  afterAll(() => {
    console.log(
      JSON.stringify({
        kind: "device-horizon-node-measurement",
        node: process.versions.node,
        measured_at: new Date().toISOString(),
        ceiling_seconds: DEVICE_HORIZON_SOLVE_CEILING_SECONDS,
        repeats,
        pools: datasets.map(({ pool, fixture }) => ({
          pool,
          players: fixture.document.players.length,
          clubs: new Set(fixture.document.players.map((player) => player.team)).size,
          members: fixture.members.length,
          server_reference: fixture.members.every(
            (member) => member.reference?.["3"] && member.reference?.["5"],
          ),
          by_member: fixture.members.map((member) => ({
            member: member.entry_id,
            windows: [3, 5].map((window) => ({
              window,
              ...summary(
                samples
                  .filter(
                    (sample) =>
                      sample.pool === pool &&
                      sample.member === member.entry_id &&
                      sample.window === window,
                  )
                  .map((sample) => sample.seconds),
              ),
            })),
          })),
          windows: [3, 5].map((window) => ({
            window,
            ...summary(
              samples
                .filter((sample) => sample.pool === pool && sample.window === window)
                .map((sample) => sample.seconds),
            ),
          })),
        })),
        samples,
      }),
    );
  });

  for (const { pool, fixture } of datasets) {
    for (const member of fixture.members) {
      for (const window of [3, 5] as const) {
        it(`${pool}, member ${member.entry_id}, H${window}`, () => {
          expect(fixture.document.season).toBe("2026-27");
          for (let repetition = 0; repetition < repeats; repetition += 1) {
            const started = performance.now();
            try {
              const answer = solveHorizon(
                withinCeiling(highs, DEVICE_HORIZON_SOLVE_CEILING_SECONDS),
                fixture.document,
                member.entry,
                window,
              );
              const seconds = (performance.now() - started) / 1000;
              samples.push({ pool, member: member.entry_id, window, seconds });
              expect(seconds).toBeLessThan(DEVICE_HORIZON_SOLVE_CEILING_SECONDS);
              const reference = member.reference?.[String(window)];
              if (reference) {
                expect(Math.abs(answer.objective - reference.objective)).toBeLessThanOrEqual(1e-6);
                expect(answer.objective_scaled).toBe(reference.objective_scaled);
              }
            } catch (error) {
              console.log(
                JSON.stringify({
                  kind: "device-horizon-node-failure",
                  pool,
                  member: member.entry_id,
                  window,
                  repetition,
                  elapsed_seconds: (performance.now() - started) / 1000,
                  status: String(error),
                }),
              );
              throw error;
            }
          }
        }, 240_000);
      }
    }
  }
});
