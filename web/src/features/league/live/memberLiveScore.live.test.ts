// @vitest-environment node
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

import { PUBLIC_ROOT } from "../../../testSupport/shippedTrees";
import type { FixturesPayload } from "../../fixtures/types";
import type { DevicePlanDocument } from "../device/types";
import { devicePlanTable } from "../directory";
import { createForwarderClient } from "../forwarder/client";
import type { LeagueViewEnvelope } from "../types";
import { memberLiveScore } from "./memberLiveScore";

// Explicit release acceptance only. Normal CI stays offline.
const origin = process.env.LIVE_SCORE_PARITY?.trim() ?? "";
it.skipIf(!origin)(
  "every published member's finished live score equals FPL after hits",
  async () => {
    const data = join(PUBLIC_ROOT, "data");
    const json = (path: string) => JSON.parse(readFileSync(join(data, path), "utf8"));
    const directory = json("leagues.json") as {
      payload: {
        leagues: {
          league_id: number;
          path: string;
          device_plan?: string;
          device_plan_sha256?: string;
        }[];
      };
    };
    const line = directory.payload.leagues.find((league) => league.league_id === 352490)!;
    const ref = devicePlanTable(line.device_plan, line.device_plan_sha256)!;
    expect(ref).toBeDefined();
    const bytes = readFileSync(join(data, ref.path));
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(ref.sha256);
    const table = (JSON.parse(bytes.toString("utf8")) as LeagueViewEnvelope<DevicePlanDocument>)
      .payload;
    const fixtures = (json("fixtures.json") as { payload: FixturesPayload }).payload;
    const members = json(line.path + "/members.json") as {
      payload: { members: { entry_id: number }[] };
    };
    const client = createForwarderClient({ root: new URL("/api/v1/fpl", origin).href });
    const rows: { entry: number; week: number; expected: number; actual: number }[] = [];
    for (const { entry_id: entry } of members.payload.members) {
      const bundle = await client.entryBundle(entry, table.gameweek, { timeoutMs: 40_000 });
      if (!bundle.ok) throw new Error("entry " + entry + ": " + bundle.reason);
      const member = bundle.document.current_week;
      expect(member).not.toBeNull();
      if (!member) continue;
      const answer = await client.liveWeek(member.gameweek);
      if (!answer.ok) throw new Error("live week: " + answer.reason);
      expect(answer.document.fixtures.every((fixture) => fixture.finished)).toBe(true);
      const result = memberLiveScore({ live: answer.document, member, table, fixtures });
      if (!result.ok) throw new Error("score: " + result.reason);
      expect(member.entry_history_points).toBeDefined();
      const expected = member.entry_history_points! - member.transfer_cost;
      rows.push({ entry, week: member.gameweek, expected, actual: result.live.score.net });
      expect(result.live.score.net, "entry " + entry).toBe(expected);
    }
    expect(rows.length).toBeGreaterThan(0);
    process.stdout.write(JSON.stringify({ members: rows.length, rows }, null, 2) + "\n");
  },
  180_000,
);
