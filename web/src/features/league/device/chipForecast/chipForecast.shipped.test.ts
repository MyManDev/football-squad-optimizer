/**
 * The device's chip timing is the shipped tree's. For every member of every published
 * full-menu tree whose entry carries the device inputs, the reading is computed from what
 * the page itself reads (the capture's table, the member's entry and the fixture
 * calendar) and must be the `chip_forecast` the publisher wrote into the member's index:
 * every status, code, verdict, gameweek and player exactly, every number to 1e-6. The
 * gains are the published chip documents' own, as the publisher reads them; one member is
 * also read end to end through the device's own 1 + n solves. A full-menu tree whose
 * index carries no `chip_forecast` fails here: the parity reference is gone, and a guard
 * that skips would ship the device's reading unchecked.
 */

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { PUBLIC_ROOT, shippedTrees } from "../../../../testSupport/shippedTrees";
import type { FixturesPayload } from "../../../fixtures/types";
import type { EntryAdviceIndex, EntrySquad, LeagueViewEnvelope } from "../../types";
import type { LpSolver } from "../lp/problem";
import { solveRequest } from "../requests";
import { isDevicePlanDocument, isDevicePlanEntry, type DevicePlanDocument } from "../types";
import { heldChips, memberChipForecast } from "./member";
import type { ChipName } from "./rule";

const require = createRequire(import.meta.url);
const read = <T>(path: string): T => JSON.parse(readFileSync(path, "utf-8")) as T;

interface Member {
  entryId: number;
  squad: EntrySquad;
  published: Record<string, unknown>;
  /** The published chip documents' gains, an unreadable one as unknown. */
  gains: Partial<Record<ChipName, number | null>>;
}

/**
 * The tree's members with device inputs and a member index, each with its published
 * reading and gains. A tree with no member index is not a full-menu tree and holds no
 * reference; a full-menu tree whose index lacks the reading is an error.
 */
function members(root: string): Member[] {
  if (!existsSync(join(root, "entries")) || !existsSync(join(root, "advice"))) return [];
  const found: Member[] = [];
  for (const name of readdirSync(join(root, "entries"))) {
    const match = /^(\d+)\.json$/.exec(name);
    if (!match) continue;
    const entryId = Number(match[1]);
    const squad = read<LeagueViewEnvelope<EntrySquad>>(join(root, "entries", name)).payload;
    const indexPath = join(root, "advice", String(entryId), "index.json");
    if (!isDevicePlanEntry(squad.device_plan) || !existsSync(indexPath)) continue;
    const index = read<LeagueViewEnvelope<EntryAdviceIndex>>(indexPath).payload;
    if (index.chip_forecast === undefined || index.chip_forecast === null) {
      throw new Error(`${indexPath} carries no chip_forecast to hold the device to.`);
    }
    const gains: Member["gains"] = {};
    const paths = index.chips?.available ? index.chips.paths : {};
    for (const [chip, path] of Object.entries(paths)) {
      const choice = read<LeagueViewEnvelope<{ chip_choice?: { gain_vs_no_chip?: unknown } }>>(
        join(root, path),
      ).payload.chip_choice;
      const gain = choice?.gain_vs_no_chip;
      gains[chip as ChipName] = typeof gain === "number" ? gain : null;
    }
    found.push({
      entryId,
      squad,
      published: index.chip_forecast as Record<string, unknown>,
      gains,
    });
  }
  return found;
}

/** The tables the page's loader may read for a member: the capture's own, and the tree's copy. */
function tables(path: string, root: string): Array<{ name: string; table: DevicePlanDocument }> {
  const found: Array<{ name: string; table: DevicePlanDocument }> = [];
  const directory = join(PUBLIC_ROOT, "data", "leagues.json");
  if (existsSync(directory)) {
    const leagues = read<{ payload: { leagues: Array<{ path: string; device_plan?: string }> } }>(
      directory,
    ).payload.leagues;
    const line = leagues.find((league) => `data/${league.path}` === path);
    if (line?.device_plan !== undefined) {
      const table = read<LeagueViewEnvelope<unknown>>(join(PUBLIC_ROOT, "data", line.device_plan));
      if (isDevicePlanDocument(table.payload)) {
        found.push({ name: line.device_plan, table: table.payload });
      }
    }
  }
  const copy = read<LeagueViewEnvelope<unknown>>(join(root, "device-plan.json")).payload;
  if (isDevicePlanDocument(copy)) found.push({ name: "device-plan.json", table: copy });
  return found;
}

const FLOATS = new Set([
  "holding_value",
  "gain_this_week",
  "threshold_this_week",
  "estimated_gain",
  "threshold",
]);

/**
 * The device's reading against the published one: the same keys at every level, the
 * rule's own numbers to 1e-6, and everything else (codes, verdicts, gameweeks, players,
 * flags) exactly. The published document's `limits` are English caveats the device
 * never states, so they are the one key left out.
 */
function expectSameReading(device: unknown, published: unknown, at: string): void {
  if (Array.isArray(published)) {
    expect(Array.isArray(device), at).toBe(true);
    expect((device as unknown[]).length, at).toBe(published.length);
    published.forEach((item, index) =>
      expectSameReading((device as unknown[])[index], item, `${at}[${index}]`),
    );
    return;
  }
  if (typeof published === "object" && published !== null) {
    expect(typeof device === "object" && device !== null && !Array.isArray(device), at).toBe(true);
    const keys = Object.keys(published).filter(
      (key) => !(at.endsWith(".forecast") && key === "limits"),
    );
    expect(Object.keys(device as object).sort(), at).toEqual(keys.sort());
    for (const key of keys) {
      const value = (published as Record<string, unknown>)[key];
      const mine = (device as Record<string, unknown>)[key];
      const path = `${at}.${key}`;
      if (FLOATS.has(key) && typeof value === "number") {
        expect(typeof mine, path).toBe("number");
        expect(Math.abs((mine as number) - value), path).toBeLessThanOrEqual(1e-6);
      } else {
        expectSameReading(mine, value, path);
      }
    }
    return;
  }
  expect(device, at).toStrictEqual(published);
}

const fixtures = (() => {
  const path = join(PUBLIC_ROOT, "data", "fixtures.json");
  return existsSync(path) ? read<{ payload: FixturesPayload }>(path).payload : null;
})();

const trees = shippedTrees().map(({ path, root }) => ({ path, root, members: members(root) }));
const fullMenu = trees.filter((tree) => tree.members.length > 0);

it("the site publishes at least one full-menu tree to hold the device to", () => {
  // The day no tree carries a member index, this file has no reference left and is retired
  // on purpose, not by an empty loop.
  expect(fullMenu.length).toBeGreaterThan(0);
});

it("a full-menu tree whose member index carries no chip_forecast fails, not skips", () => {
  const root = mkdtempSync(join(tmpdir(), "chip-forecast-tree-"));
  mkdirSync(join(root, "entries"));
  mkdirSync(join(root, "advice", "7"), { recursive: true });
  const envelope = (payload: unknown) => JSON.stringify({ payload });
  writeFileSync(
    join(root, "entries", "7.json"),
    envelope({ device_plan: { held: [], bank_tenths: 0, free_transfers: 1, sell_tenths: {} } }),
  );
  writeFileSync(join(root, "advice", "7", "index.json"), envelope({ entry_id: 7 }));
  try {
    expect(() => members(root)).toThrow(/carries no chip_forecast/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

for (const { path, root, members: shipped } of fullMenu) {
  describe(path, () => {
    for (const { name, table } of tables(path, root)) {
      it.each(shipped.map((member) => [member.entryId, name, member] as const))(
        "entry %i reads the published chip timing from %s",
        (_, __, { squad, published, gains }) => {
          const device = memberChipForecast({ table, squad, fixtures, gains });
          expectSameReading(device, published, "chip_forecast");
        },
      );
    }
  });
}

/**
 * The member the device solves end to end: one with a chip to play now, if any has one.
 * One member is enough here: `planModel.chips.shipped.test.ts` already holds every chip
 * gain of the tree to its published document, and each solve costs seconds.
 */
function solvedMember(): { root: string; member: Member } | undefined {
  const all = fullMenu.flatMap(({ root, members: shipped }) =>
    shipped.map((member) => ({ root, member })),
  );
  const playNow = all.find(({ member }) =>
    JSON.stringify(member.published.forecast ?? null).includes('"play_now"'),
  );
  return playNow ?? all[0];
}

describe("the device's own chip gains", () => {
  let solver: LpSolver;
  beforeAll(async () => {
    const wasm = readFileSync(require.resolve("highs/runtime"));
    const load = (await import("highs")).default;
    solver = (await load({ wasmBinary: wasm })) as unknown as LpSolver;
  }, 60_000);

  it("give the published reading through the worker's 1 + n request", () => {
    const { root, member } = solvedMember()!;
    const { squad, published, gains } = member;
    const table = read<LeagueViewEnvelope<DevicePlanDocument>>(
      join(root, "device-plan.json"),
    ).payload;
    const chips = heldChips(squad.chips, table.gameweek)!;
    expect(chips.length).toBeGreaterThan(0);
    const answer = solveRequest(solver, {
      document: table,
      entry: squad.device_plan!,
      chipGains: chips,
    });
    expect(answer.chip).toBeNull();
    const solved = answer.chip_gains!;
    expect(Object.keys(solved)).toEqual(chips);
    for (const chip of chips) {
      if (gains[chip] == null) expect(solved[chip]).toBeNull();
      else expect(solved[chip]).toBeCloseTo(gains[chip], 6);
    }
    const device = memberChipForecast({ table, squad, fixtures, gains: solved });
    expectSameReading(device, published, "chip_forecast");
  }, 180_000);
});
