/**
 * The what-if mode reads the shipped tree's plans as the tree publishes them (#1132). For
 * every human member of every published league tree whose entry document carries the
 * device block, the published one-week pure-points plan (`saf-puan/1.json`) is the
 * fifteen the mode starts from; read on the mode's terms it must have the plan's own
 * points, its hit and as many transfers as the plan has moves, and break no rule. A
 * member the mode cannot start for is listed with the reason, never passed over.
 */
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { shippedTrees } from "../../../testSupport/shippedTrees";
import type { EntryAdvice, EntrySquad, LeagueMembers, LeagueViewEnvelope } from "../types";
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

for (const { path, root } of shippedTrees()) {
  describe(path, () => {
    const read = <T>(relative: string): T =>
      JSON.parse(readFileSync(join(root, relative), "utf-8")) as T;
    if (!existsSync(join(root, "device-plan.json"))) {
      it.skip("publishes no device-plan.json", () => {});
      return;
    }
    const document = whatIfDocument(
      read<LeagueViewEnvelope<DevicePlanDocument>>("device-plan.json").payload,
    );
    const members = read<LeagueViewEnvelope<LeagueMembers>>("members.json").payload.members;
    const cases: { entryId: number; squad: EntrySquad; plan: EntryAdvice; advised: number[] }[] =
      [];
    const passed: string[] = [];
    for (const member of members) {
      if (member.member_kind !== "human") continue;
      const squad = read<LeagueViewEnvelope<EntrySquad>>(`entries/${member.entry_id}.json`).payload;
      const relative = `advice/${member.entry_id}/saf-puan/1.json`;
      if (!isDevicePlanEntry(squad.device_plan)) {
        passed.push(`${member.entry_id}: no device block`);
        continue;
      }
      if (!existsSync(join(root, relative))) {
        passed.push(`${member.entry_id}: no published one-week plan`);
        continue;
      }
      const plan = read<LeagueViewEnvelope<EntryAdvice>>(relative).payload;
      const advised = advisedFifteen(plan);
      if (advised === null) {
        passed.push(`${member.entry_id}: the plan is not a solved week without a chip`);
        continue;
      }
      cases.push({ entryId: member.entry_id, squad, plan, advised });
    }

    it("starts from at least one member's plan, and names every member it does not", () => {
      expect(cases.length).toBeGreaterThan(0);
      expect(cases.length + passed.length).toBe(
        members.filter((member) => member.member_kind === "human").length,
      );
    });

    for (const { entryId, squad, plan, advised } of cases) {
      it(`reads ${entryId}'s plan with the plan's points, hit and transfers`, () => {
        expect(squad.source_snapshot_id).toBe(document.source_snapshot_id);
        const [points] = whatIfValues(solver, document, [advised]);
        expect(points).toBeCloseTo(plan.expected_own_points!, 6);
        const account = whatIfAccount(document, squad.device_plan!, advised);
        expect(account.breaks).toEqual([]);
        expect(account.hitPoints).toBe(plan.transfer_hit_points);
        expect(account.transfers).toBe(plan.moves.length);
        expect(account.bankTenths).toBeGreaterThanOrEqual(0);
      });
    }
  });
}
