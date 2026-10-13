// @vitest-environment node
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import fixture from "../fixtures/device-plan/instances.json";
import { devicePlanTableProblems, shippedDevicePlanLines } from "./shippedDevicePlanTables";

// Today's committed site names no table, so the shipped check is vacuous until the first
// publish that writes one. These hold the check itself to finding what it is for.

const CAPTURE = "fpl-live-20261016T060000Z-0123456789ab";
const TABLE_PATH = `device/${CAPTURE}/device-plan.json`;
const LEAGUE = fixture.document.league_id;

let root: string;

function envelope(payload: unknown) {
  return {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-10-16T08:00:00Z",
    source_kind: "live",
    payload,
  };
}

function copy(): Record<string, unknown> {
  return { ...fixture.document, source_snapshot_id: CAPTURE };
}

/** The table as the run publishes it: the copy without its league, four fields more. */
function table(): Record<string, unknown> {
  const { league_id: _league, ...shared } = fixture.document;
  return {
    ...shared,
    contract_version: "league_device_plan_v2",
    source_snapshot_id: CAPTURE,
    rules: { ...shared.rules, chips: [], transfers_cap: null },
    players: shared.players.map((player, index) => ({
      ...player,
      element_id: index + 1,
      start_tenths: player.buy_tenths,
    })),
  };
}

/** Write a file under the site's `data/` and return the sha256 of its bytes. */
function put(relative: string, value: unknown): string {
  const path = join(root, "data", ...relative.split("/"));
  mkdirSync(join(path, ".."), { recursive: true });
  const text = `${JSON.stringify(value, null, 2)}\n`;
  writeFileSync(path, text);
  return createHash("sha256").update(text, "utf8").digest("hex");
}

/** A site of one league whose line names the table with `digest`. */
function site(line: Record<string, unknown>) {
  put("leagues.json", {
    contract_version: "league_directory_v1",
    payload: {
      leagues: [
        {
          league_id: LEAGUE,
          league_name: "One",
          season: "2026-27",
          gameweek: 7,
          path: `leagues/${LEAGUE}`,
          ...line,
        },
      ],
    },
  });
  return shippedDevicePlanLines(root);
}

function problems(tableDocument: unknown, line?: Record<string, unknown>): string[] {
  put(`leagues/${LEAGUE}/device-plan.json`, envelope(copy()));
  const digest = put(TABLE_PATH, envelope(tableDocument));
  const lines = site(line ?? { device_plan: TABLE_PATH, device_plan_sha256: digest });
  expect(lines).toHaveLength(1);
  return devicePlanTableProblems(lines[0]!, root);
}

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "shipped-device-tables-"));
});
afterEach(() => rmSync(root, { recursive: true, force: true }));

describe("the shipped device-plan table check", () => {
  it("passes the table the run publishes beside the tree's copy", () => {
    expect(problems(table())).toEqual([]);
  });

  it("lists no line from before the table", () => {
    expect(site({})).toEqual([]);
  });

  it("finds a table whose bytes another digest names, or that is gone", () => {
    const other = "0".repeat(64);
    expect(problems(table(), { device_plan: TABLE_PATH, device_plan_sha256: other })).toEqual([
      expect.stringContaining(`the line names ${other}`),
    ]);
    rmSync(join(root, "data", ...TABLE_PATH.split("/")));
    expect(devicePlanTableProblems(shippedDevicePlanLines(root)[0]!, root)).toEqual([
      `${TABLE_PATH} is missing`,
    ]);
  });

  it("finds a line the page would not read", () => {
    const digest = "a".repeat(64);
    for (const line of [
      { device_plan: `leagues/${LEAGUE}/device-plan.json`, device_plan_sha256: digest },
      { device_plan: TABLE_PATH, device_plan_sha256: digest.toUpperCase() },
      { device_plan: TABLE_PATH },
      { device_plan_sha256: digest },
    ]) {
      expect(problems(table(), line)).toEqual([
        expect.stringContaining("which the page does not read"),
      ]);
    }
  });

  it("finds a table the page's validator refuses", () => {
    const expected = [expect.stringContaining("not a league_device_plan_v2 document")];
    // The tree's copy published where the table belongs.
    expect(problems(copy())).toEqual(expected);
    const noElement = table() as { players: Record<string, unknown>[] };
    delete noElement.players[0]!.element_id;
    expect(problems(noElement)).toEqual(expected);
    expect(problems({ ...table(), league_id: LEAGUE })).toEqual(expected);
  });

  it("finds a table that is not the tree's copy plus its own fields", () => {
    const drifted = table() as { players: Record<string, unknown>[] };
    drifted.players[1] = { ...drifted.players[1], expected_points: 99 };
    expect(problems(drifted)).toEqual([expect.stringContaining("players[1] differ")]);
    const reordered = table() as { players: unknown[] };
    reordered.players.reverse();
    expect(problems(reordered)).toEqual([expect.stringContaining("players[0] differ")]);
  });

  it("finds a table of another capture than its path names", () => {
    expect(problems({ ...table(), source_snapshot_id: "fpl-live-other" })).toEqual([
      `${TABLE_PATH} holds capture fpl-live-other`,
      expect.stringContaining("source_snapshot_id differ"),
    ]);
  });

  it("finds a tree with no copy to hold the table to", () => {
    const digest = put(TABLE_PATH, envelope(table()));
    const lines = site({ device_plan: TABLE_PATH, device_plan_sha256: digest });
    expect(devicePlanTableProblems(lines[0]!, root)).toEqual([
      `leagues/${LEAGUE}/device-plan.json, the tree's copy, is missing`,
    ]);
  });
});
