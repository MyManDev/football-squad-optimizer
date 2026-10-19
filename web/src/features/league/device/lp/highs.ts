/**
 * The solver a worker loads once: HiGHS with its wasm binary from the app's own assets,
 * so nothing is fetched from anywhere but the site. A load that failed is tried again on
 * the next request.
 */

import loadHighs from "highs";
import wasmUrl from "highs/runtime?url";

import type { LpSolver } from "./problem";

let solver: Promise<LpSolver> | null = null;

export function highs(): Promise<LpSolver> {
  solver ??= (loadHighs({ locateFile: () => wasmUrl }) as unknown as Promise<LpSolver>).catch(
    (error: unknown) => {
      solver = null;
      throw error;
    },
  );
  return solver;
}
