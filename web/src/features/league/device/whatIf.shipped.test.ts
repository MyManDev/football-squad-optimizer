/**
 * The what-if mode reads the shipped tree's plans as the tree publishes them (#1132). For
 * every human member of every published league tree whose entry document carries the
 * device block, every advice document the mode is offered for (a solved one-week plan on
 * base points: the pure-points plan and each rival plan) is read on the mode's terms: it
 * must have the plan's own points, its hit and as many transfers as the plan has moves,
 * and break no rule. The documents it is not offered for are counted, never read on a
 * basis that is not theirs.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join, relative } from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { shippedTrees } from "../../../testSupport/shippedTrees";
import type {
  EntryAdvice,
  EntryAdviceIndex,
  EntrySquad,
  LeagueMembers,
  LeagueViewEnvelope,
} from "../types";
import type { LpSolver } from "./lp/problem";
import { isDevicePlanEntry, type DevicePlanDocument } from "./types";
import { advisedFifteen, whatIfAccount, whatIfDocument, whatIfValues } from "./whatIf";

const require = createRequire(import.meta.url);
let solver: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  solver = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);

/** Every advice document under a member's folder, by its path in the tree. */
function adviceDocuments(root: string, entryId: number): string[] {
  const base = join(root, "advice", String(entryId));
  if (!existsSync(base)) return [];
  const found: string[] = [];
  const walk = (folder: string) => {
    for (const item of readdirSync(folder, { withFileTypes: true })) {
      const full = join(folder, item.name);
      if (item.isDirectory()) walk(full);
      else if (item.name.endsWith(".json") && item.name !== "index.json")
        found.push(relative(root, full));
    }
  };
  walk(base);
  return found.sort();
}

for (const { path, root } of shippedTrees()) {
  describe(path, () => {
    const read = <T>(file: string): T => JSON.parse(readFileSync(join(root, file), "utf-8")) as T;
    if (!existsSync(join(root, "device-plan.json"))) {
      it.skip("publishes no device-plan.json", () => {});
      return;
    }
    const document = whatIfDocument(
      read<LeagueViewEnvelope<DevicePlanDocument>>("device-plan.json").payload,
    );
    const members = read<LeagueViewEnvelope<LeagueMembers>>("members.json").payload.members;
    const cases: { file: string; squad: EntrySquad; plan: EntryAdvice; advised: number[] }[] = [];
    let declined = 0;
    let deviceMembers = 0;
    for (const member of members) {
      if (member.member_kind !== "human") continue;
      const index = read<LeagueViewEnvelope<EntryAdviceIndex>>(
        `advice/${member.entry_id}/index.json`,
      ).payload;
      if (index.menu === "device") {
        deviceMembers += 1;
        continue;
      }
      const squad = read<LeagueViewEnvelope<EntrySquad>>(`entries/${member.entry_id}.json`).payload;
      if (!isDevicePlanEntry(squad.device_plan)) continue;
      for (const file of adviceDocuments(root, member.entry_id)) {
        const plan = read<LeagueViewEnvelope<EntryAdvice>>(file).payload;
        const advised = advisedFifteen(plan);
        if (advised === null) declined += 1;
        else cases.push({ file, squad, plan, advised });
      }
    }

    it("offers the mode on the one-week base plans and declines every other document", () => {
      if (deviceMembers === members.filter((member) => member.member_kind === "human").length) {
        expect(cases).toEqual([]);
        expect(declined).toBe(0);
        return;
      }
      expect(cases.length).toBeGreaterThan(0);
      expect(declined).toBeGreaterThan(0);
      for (const { plan } of cases) {
        expect([plan.window, plan.top100, plan.evidence, plan.chip ?? null]).toEqual([
          1,
          undefined,
          undefined,
          null,
        ]);
      }
    });

    it.each(cases.map((item) => [item.file, item] as const))(
      "reads %s with the plan's own points, hit and transfers",
      (_, { squad, plan, advised }) => {
        expect(squad.source_snapshot_id).toBe(document.source_snapshot_id);
        const [points] = whatIfValues(solver, document, [advised]);
        expect(points).toBeCloseTo(plan.expected_own_points!, 6);
        const account = whatIfAccount(document, squad.device_plan!, advised);
        expect(account.breaks).toEqual([]);
        expect(account.hitPoints).toBe(plan.transfer_hit_points);
        expect(account.transfers).toBe(plan.moves.length);
        expect(account.bankTenths).toBeGreaterThanOrEqual(0);
      },
    );
  });
}
