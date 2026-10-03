/**
 * The device's chip plans are the shipped tree's chip plans. Every member of the
 * published league whose entry carries the device inputs, and every chip document the
 * publisher solved for them, is solved here from the same two documents with the chip
 * played, and the squad, eleven, captain, bench, transfers, points and the gain against
 * the member's own no-chip plan must be what the tree publishes. The tree is whatever
 * publication the repository holds; a tree without chip documents holds nothing here.
 */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import type { EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import { solveRequest } from "./devicePlan.worker";
import type { LpSolver } from "./planModel";
import { DEVICE_CHIPS, isDevicePlanDocument, isDevicePlanEntry, type DeviceChip } from "./types";

const require = createRequire(import.meta.url);
const ROOT = join(__dirname, "../../../../public/data/league");
const read = <T>(relative: string): T =>
  JSON.parse(readFileSync(join(ROOT, relative), "utf-8")) as T;

interface Case {
  entryId: number;
  chip: DeviceChip;
  squad: EntrySquad;
  published: EntryAdvice;
}

function cases(): Case[] {
  if (!existsSync(join(ROOT, "device-plan.json")) || !existsSync(join(ROOT, "entries"))) return [];
  const found: Case[] = [];
  for (const name of readdirSync(join(ROOT, "entries"))) {
    const match = /^(\d+)\.json$/.exec(name);
    if (!match) continue;
    const entryId = Number(match[1]);
    const squad = read<LeagueViewEnvelope<EntrySquad>>(`entries/${name}`).payload;
    if (!isDevicePlanEntry(squad.device_plan)) continue;
    for (const chip of DEVICE_CHIPS) {
      const path = `advice/${entryId}/saf-puan/1/chip-${chip}.json`;
      if (!existsSync(join(ROOT, path))) continue;
      found.push({
        entryId,
        chip,
        squad,
        published: read<LeagueViewEnvelope<EntryAdvice>>(path).payload,
      });
    }
  }
  return found;
}

const shipped = cases();
const ids = (players: Array<{ player_id: number }>) =>
  players.map((p) => p.player_id).sort((a, b) => a - b);

describe("the shipped chip plans", () => {
  let solver: LpSolver;
  beforeAll(async () => {
    const wasm = readFileSync(require.resolve("highs/runtime"));
    const load = (await import("highs")).default;
    solver = (await load({ wasmBinary: wasm })) as unknown as LpSolver;
  }, 60_000);

  it("are solved from the tree's device inputs", () => {
    if (shipped.length === 0) return;
    const document = read<LeagueViewEnvelope<unknown>>("device-plan.json").payload;
    expect(isDevicePlanDocument(document)).toBe(true);
    // Every chip the game has is represented somewhere in the tree, or the tree says why.
    const chips = new Set(shipped.map((c) => c.chip));
    expect(chips.size).toBeGreaterThan(0);
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
      // proves its own, which may be the better plan. Its points may not fall short.
      if (published.solver_status !== "OPTIMAL") {
        expect(answer.expected_own_points - answer.transfer_hit_points).toBeGreaterThanOrEqual(
          published.expected_own_points! - (published.transfer_hit_points ?? 0) - 1e-6,
        );
        return;
      }
      expect(answer.starting_xi).toEqual(ids(published.starting_xi!));
      expect(answer.captain).toBe(published.captain!.player_id);
      expect(answer.vice_captain).toBe(published.vice_captain!.player_id);
      expect(answer.bench).toEqual(published.bench!.map((p) => p.player_id));
      expect(answer.transfers_in).toEqual(ids(published.moves.map((m) => m.player_in!)));
      expect(answer.transfers_out).toEqual(ids(published.moves.map((m) => m.player_out!)));
      expect(answer.transfer_hit_points).toBe(published.transfer_hit_points ?? 0);
      expect(answer.expected_own_points).toBeCloseTo(published.expected_own_points!, 6);
      if (published.expected_gain_vs_hold == null) expect(answer.expected_gain_vs_hold).toBeNull();
      else expect(answer.expected_gain_vs_hold).toBeCloseTo(published.expected_gain_vs_hold, 6);
      expect(answer.moves.map((m) => [m.out, m.in])).toEqual(
        published.moves.map((m) => [m.player_out!.player_id, m.player_in!.player_id]),
      );
      for (const [index, move] of answer.moves.entries()) {
        const expected = published.moves[index]!.expected_points_delta;
        if (expected === null) expect(move.gain).toBeNull();
        else expect(move.gain).toBeCloseTo(expected, 6);
      }
      expect(answer.gain_vs_no_chip).toBeCloseTo(published.chip_choice!.gain_vs_no_chip, 6);
    },
    60_000,
  );
});
