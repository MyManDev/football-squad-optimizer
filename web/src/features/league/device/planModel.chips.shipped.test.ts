/**
 * The device's chip plans are the shipped tree's chip plans. Every member of the
 * published league whose entry carries the device inputs, and every chip document the
 * publisher solved for them, is solved here from the same two documents with the chip
 * played, and the squad, eleven, captain, bench, transfers, points and the gain against
 * the member's own no-chip plan must be what the tree publishes. The trees are whatever
 * publication the repository holds (`testSupport/shippedTrees.ts`); a tree without chip
 * documents holds nothing here.
 */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { shippedTrees } from "../../../testSupport/shippedTrees";
import type { EntryAdvice, EntryAdviceIndex, EntrySquad, LeagueViewEnvelope } from "../types";
import type { LpSolver } from "./lp/problem";
import { solveRequest } from "./requests";
import { rebuilds } from "./strategies/chips";
import {
  isDeviceChip,
  isDevicePlanDocument,
  isDevicePlanEntry,
  type DeviceChip,
  type DevicePlanDocument,
} from "./types";

const require = createRequire(import.meta.url);
/** A document of one published tree. */
const reader =
  (root: string) =>
  <T>(relative: string): T =>
    JSON.parse(readFileSync(join(root, relative), "utf-8")) as T;

interface Case {
  entryId: number;
  chip: DeviceChip;
  squad: EntrySquad;
  published: EntryAdvice;
}

/** The tree's members with device inputs, and every chip document each one's index names. */
function cases(ROOT: string): { cases: Case[]; withInputs: number } {
  const read = reader(ROOT);
  if (!existsSync(join(ROOT, "device-plan.json")) || !existsSync(join(ROOT, "entries"))) {
    return { cases: [], withInputs: 0 };
  }
  const found: Case[] = [];
  let withInputs = 0;
  for (const name of readdirSync(join(ROOT, "entries"))) {
    const match = /^(\d+)\.json$/.exec(name);
    if (!match) continue;
    const entryId = Number(match[1]);
    const squad = read<LeagueViewEnvelope<EntrySquad>>(`entries/${name}`).payload;
    if (!isDevicePlanEntry(squad.device_plan)) continue;
    withInputs += 1;
    // The index is the authority on which chip documents the publish wrote; a document
    // it names must be there, so a publish that drops one fails here, not silently.
    const index = read<LeagueViewEnvelope<EntryAdviceIndex>>(
      `advice/${entryId}/index.json`,
    ).payload;
    const paths = index.chips?.available ? (index.chips.paths ?? {}) : {};
    for (const [chip, path] of Object.entries(paths)) {
      if (!isDeviceChip(chip)) continue;
      found.push({
        entryId,
        chip,
        squad,
        published: read<LeagueViewEnvelope<EntryAdvice>>(String(path)).payload,
      });
    }
  }
  return { cases: found, withInputs };
}

const trees = shippedTrees()
  .map(({ path, root }) => ({ path, root, tree: cases(root) }))
  .filter(({ tree }) => tree.cases.length > 0);
const ids = (players: Array<{ player_id: number }>) => players.map((p) => p.player_id);

/**
 * A player as the planner sees him: position, price and objective coefficients. Two
 * players alike in all three are interchangeable, and an optimum may hold either: the
 * first weekly-run tree under the directory had the server bench one 4.0 goalkeeper and
 * the device another with the same coefficients, on an otherwise identical Wildcard.
 * Plans are compared by these keys and nothing looser; every number must still match.
 */
function plannerKey(document: DevicePlanDocument): (id: number | null) => string {
  const keys = new Map(
    document.players.map((p) => [
      p.id,
      `${p.position}|${p.buy_tenths}|${p.coefficients.join(",")}`,
    ]),
  );
  return (id) => (id === null ? "no player" : (keys.get(id) ?? `player ${id}`));
}

/**
 * The planner's objective of a published plan, on the document's integer scale: the
 * squad coefficients over the fifteen, the starter coefficients over the eleven, the
 * captain's, each as the chip reads them, less the caution margin per paid transfer.
 * What the device maximises, so a proven device plan may not fall below it.
 */
function publishedObjective(
  document: DevicePlanDocument,
  published: EntryAdvice,
  chip: DeviceChip,
  freeTransfers: number,
): number {
  const byId = new Map(document.players.map((p) => [p.id, p.coefficients]));
  const eleven = new Set(published.starting_xi!.map((p) => p.player_id));
  const fifteen = [...published.starting_xi!, ...published.bench!].map((p) => p.player_id);
  let total = 0;
  for (const id of fifteen) {
    const [squad, starter, captain] = byId.get(id)!;
    total += chip === "bboost" ? squad + Math.max(starter, 0) : squad;
    if (eleven.has(id)) total += chip === "bboost" ? Math.min(starter, 0) : starter;
    if (id === published.captain!.player_id) {
      total += chip === "3xc" ? captain + Math.max(captain, 0) : captain;
    }
  }
  const paid = rebuilds(chip) ? 0 : Math.max(0, published.moves.length - freeTransfers);
  return total - document.rules.hit_cost_scaled * paid;
}

describe.skipIf(trees.length === 0)("the shipped chip plans", () => {
  let solver: LpSolver;
  beforeAll(async () => {
    const wasm = readFileSync(require.resolve("highs/runtime"));
    const load = (await import("highs")).default;
    solver = (await load({ wasmBinary: wasm })) as unknown as LpSolver;
  }, 60_000);

  for (const { path, root: ROOT, tree } of trees) {
    const read = reader(ROOT);
    const shipped = tree.cases;
    describe(path, () => {
      it("are solved from the tree's device inputs, for every member the tree wrote them for", () => {
        const document = read<LeagueViewEnvelope<unknown>>("device-plan.json").payload;
        expect(isDevicePlanDocument(document)).toBe(true);
        // Every member with device inputs has at least one chip document, or says why.
        const members = new Set(shipped.map((c) => c.entryId));
        for (const name of readdirSync(join(ROOT, "entries"))) {
          const match = /^(\d+)\.json$/.exec(name);
          if (!match) continue;
          const entryId = Number(match[1]);
          if (!members.has(entryId)) {
            const index = read<LeagueViewEnvelope<EntryAdviceIndex>>(
              `advice/${entryId}/index.json`,
            ).payload;
            expect(index.chips?.available ? Object.keys(index.chips.paths ?? {}) : []).toEqual([]);
          }
        }
        expect(members.size).toBeGreaterThan(0);
        expect(tree.withInputs).toBeGreaterThanOrEqual(members.size);
      });

      it.each(shipped.map((c) => [c.entryId, c.chip, c] as const))(
        "entry %i with %s is the device's answer",
        (_, chip, { squad, published }) => {
          const document = read<LeagueViewEnvelope<unknown>>("device-plan.json").payload;
          if (!isDevicePlanDocument(document) || !isDevicePlanEntry(squad.device_plan)) {
            throw new Error("the tree's device inputs are not the published shapes");
          }
          expect(document.source_snapshot_id).toBe(published.source_snapshot_id);
          const answer = solveRequest(solver, { document, entry: squad.device_plan, chip });
          expect(answer.chip).toBe(chip);
          expect(published.chip).toBe(chip);
          // A plan the server found without finishing its proof is not held to: the device
          // proves its own, which may be the better plan. On the planner's own objective the
          // proven plan may not fall below the published one.
          if (published.solver_status !== "OPTIMAL") {
            expect(answer.objective_scaled).toBeGreaterThanOrEqual(
              publishedObjective(document, published, chip, squad.device_plan.free_transfers) -
                1e-6,
            );
            return;
          }
          const key = plannerKey(document);
          const set = (players: number[]) => players.map(key).sort();
          expect(set(answer.starting_xi)).toEqual(set(ids(published.starting_xi!)));
          expect(key(answer.captain)).toBe(key(published.captain!.player_id));
          expect(key(answer.vice_captain)).toBe(key(published.vice_captain!.player_id));
          expect(answer.bench.map(key)).toEqual(ids(published.bench!).map(key));
          expect(set(answer.transfers_in)).toEqual(
            set(ids(published.moves.map((m) => m.player_in!))),
          );
          expect(set(answer.transfers_out)).toEqual(
            set(ids(published.moves.map((m) => m.player_out!))),
          );
          expect(answer.transfer_hit_points).toBe(published.transfer_hit_points ?? 0);
          expect(answer.expected_own_points).toBeCloseTo(published.expected_own_points!, 6);
          if (published.expected_gain_vs_hold == null)
            expect(answer.expected_gain_vs_hold).toBeNull();
          else expect(answer.expected_gain_vs_hold).toBeCloseTo(published.expected_gain_vs_hold, 6);
          const fifteen = (xi: number[], bench: number[]) =>
            [...xi, ...bench].sort((a, b) => a - b).join();
          const swapped =
            fifteen(answer.starting_xi, answer.bench) !==
            fifteen(ids(published.starting_xi!), ids(published.bench!));
          if (!swapped) {
            expect(answer.moves.map((m) => [m.out, m.in])).toEqual(
              published.moves.map((m) => [m.player_out!.player_id, m.player_in!.player_id]),
            );
            for (const [index, move] of answer.moves.entries()) {
              const expected = published.moves[index]!.expected_points_delta;
              if (expected === null) expect(move.gain).toBeNull();
              else expect(move.gain).toBeCloseTo(expected, 6);
            }
          } else {
            // Moves are paired by id within a position and scored one after another on the
            // squad so far, so a tie swapped in can move how the gain splits across rows and
            // positions; what cannot move is their sum, the plan's gain over the squad held.
            const total = (gains: Array<number | null>) =>
              gains.reduce<number>((sum, gain) => sum + (gain ?? 0), 0);
            expect(total(answer.moves.map((m) => m.gain))).toBeCloseTo(
              total(published.moves.map((m) => m.expected_points_delta)),
              6,
            );
          }
          expect(answer.gain_vs_no_chip).toBeCloseTo(published.chip_choice!.gain_vs_no_chip, 6);
        },
        60_000,
      );
    });
  }
});
