/**
 * #981 step 2: the page reads the capture's own device-plan table where the league
 * directory names one, at its sha256 as the version and held to that sha256 byte for
 * byte, and falls back to the league tree's own copy otherwise. The table names no
 * league; the tree's copy does.
 */

import { createHash } from "node:crypto";

import { afterEach, describe, expect, it, vi } from "vitest";

import fixture from "../../fixtures/device-plan/instances.json";
import { jsonResponse, stubFetchByUrl } from "../../testSupport/fetchByUrl";
import { createLeagueTree } from "./data";
import { DIRECTORY_CONTRACT_VERSION, loadLeagueDirectory, type LeagueRef } from "./directory";
import {
  DEVICE_PLAN_TABLE_CONTRACT_VERSION,
  isDevicePlanDocument,
  type DevicePlanDocument,
} from "./device/types";

afterEach(() => {
  vi.unstubAllGlobals();
});

const CAPTURE = "fpl-live-20261016T060000Z-0123456789ab";
const TABLE_PATH = `device/${CAPTURE}/device-plan.json`;

const copy = fixture.document as unknown as DevicePlanDocument & { league_id: number };

/** The capture's table as step 1 publishes it: the copy without its league, four fields more. */
function captureTable(): Record<string, unknown> {
  const { league_id: _league, ...shared } = copy;
  return {
    ...shared,
    contract_version: DEVICE_PLAN_TABLE_CONTRACT_VERSION,
    source_snapshot_id: CAPTURE,
    rules: { ...shared.rules, chips: [], transfers_cap: null },
    players: shared.players.map((player, index) => ({
      ...player,
      element_id: index + 1,
      start_tenths: player.buy_tenths,
    })),
  };
}

function envelope(payload: unknown): Record<string, unknown> {
  return {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-10-16T08:00:00Z",
    source_kind: "live",
    payload,
  };
}

function bytesOf(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

const TABLE_TEXT = bytesOf(envelope(captureTable()));
const TABLE_SHA = sha256(TABLE_TEXT);
const COPY = envelope({ ...copy, source_snapshot_id: CAPTURE });
const LATER_CAPTURE = "fpl-live-20261023T060000Z-ba9876543210";
const LATER_COPY = envelope({ ...copy, source_snapshot_id: LATER_CAPTURE });

function league(devicePlan?: LeagueRef["devicePlan"]): LeagueRef {
  return { leagueId: copy.league_id, path: `leagues/${copy.league_id}`, devicePlan };
}

describe("the directory line's device-plan table", () => {
  const line = {
    league_id: 352490,
    league_name: "Published league",
    season: "2026-27",
    gameweek: 7,
    path: "leagues/352490",
  };

  async function read(fields: Record<string, unknown>) {
    stubFetchByUrl([
      [
        "/data/leagues.json",
        () =>
          jsonResponse({
            contract_version: DIRECTORY_CONTRACT_VERSION,
            payload: { leagues: [{ ...line, ...fields }] },
          }),
      ],
    ]);
    return (await loadLeagueDirectory()).leagues[0];
  }

  it("is read with its digest", async () => {
    const read_ = await read({ device_plan: TABLE_PATH, device_plan_sha256: TABLE_SHA });
    expect(read_?.devicePlan).toEqual({ path: TABLE_PATH, sha256: TABLE_SHA });
  });

  it.each([
    ["no digest", { device_plan: TABLE_PATH }],
    ["no path", { device_plan_sha256: TABLE_SHA }],
    [
      "an upper-case digest",
      { device_plan: TABLE_PATH, device_plan_sha256: TABLE_SHA.toUpperCase() },
    ],
    ["a short digest", { device_plan: TABLE_PATH, device_plan_sha256: TABLE_SHA.slice(1) }],
    [
      "a path that is no capture table",
      { device_plan: "leagues/352490/device-plan.json", device_plan_sha256: TABLE_SHA },
    ],
    [
      "a path that climbs",
      { device_plan: "device/../device-plan.json", device_plan_sha256: TABLE_SHA },
    ],
  ])("is ignored with %s, and the league is still read", async (_name, fields) => {
    const read_ = await read(fields);
    expect(read_?.leagueId).toBe(352490);
    expect(read_?.devicePlan).toBeUndefined();
  });
});

describe("tree.devicePlan", () => {
  it("reads the capture's table at its digest, and the page may keep it", async () => {
    const fetcher = stubFetchByUrl([
      [`/data/${TABLE_PATH}?v=${TABLE_SHA}`, () => new Response(TABLE_TEXT)],
      [`/data/leagues/${copy.league_id}/device-plan.json`, () => jsonResponse(COPY)],
    ]);
    const read = await createLeagueTree(league({ path: TABLE_PATH, sha256: TABLE_SHA })).devicePlan(
      CAPTURE,
    );
    expect(read.payload.contract_version).toBe(DEVICE_PLAN_TABLE_CONTRACT_VERSION);
    expect(read.payload.league_id).toBeUndefined();
    expect(read.payload.source_snapshot_id).toBe(CAPTURE);
    const urls = fetcher.mock.calls.map(([url]) => url);
    expect(urls).toEqual([`/data/${TABLE_PATH}?v=${TABLE_SHA}`]);
    // No "no-cache": the address carries the version, so a kept answer is the right one.
    expect(fetcher.mock.calls[0]?.[1]).toEqual({ signal: expect.any(AbortSignal) });
  });

  it.each([
    [
      "bytes another digest names",
      () => new Response(TABLE_TEXT.replace('"season"', '"season" ')),
      TABLE_SHA,
    ],
    ["a missing table", () => new Response("", { status: 404 }), TABLE_SHA],
    ["a table that is the tree's copy", () => new Response(bytesOf(COPY)), sha256(bytesOf(COPY))],
    ["a table that is not JSON", () => new Response("{"), sha256("{")],
  ])("falls back to the tree's own copy on %s", async (_name, answer, digest) => {
    const fetcher = stubFetchByUrl([
      [`/data/${TABLE_PATH}?v=${digest}`, answer],
      [`/data/leagues/${copy.league_id}/device-plan.json`, () => jsonResponse(COPY)],
    ]);
    const read = await createLeagueTree(league({ path: TABLE_PATH, sha256: digest })).devicePlan(
      CAPTURE,
    );
    expect(read.payload.contract_version).toBe("league_device_plan_v1");
    expect(read.payload.league_id).toBe(copy.league_id);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      `/data/${TABLE_PATH}?v=${digest}`,
      `/data/leagues/${copy.league_id}/device-plan.json`,
    ]);
  });

  it("reads the tree's copy, not a table of another capture than the member's page", async () => {
    // The directory was read before a later publish, and the browser may keep the earlier
    // capture's table for a year: the copy is read as the tree is now.
    const fetcher = stubFetchByUrl([
      [`/data/${TABLE_PATH}?v=${TABLE_SHA}`, () => new Response(TABLE_TEXT)],
      [`/data/leagues/${copy.league_id}/device-plan.json`, () => jsonResponse(LATER_COPY)],
    ]);
    const read = await createLeagueTree(league({ path: TABLE_PATH, sha256: TABLE_SHA })).devicePlan(
      LATER_CAPTURE,
    );
    expect(read.payload.contract_version).toBe("league_device_plan_v1");
    expect(read.payload.source_snapshot_id).toBe(LATER_CAPTURE);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      `/data/leagues/${copy.league_id}/device-plan.json`,
    ]);
  });

  it("reads the tree's copy alone where the directory names no table", async () => {
    const fetcher = stubFetchByUrl([
      [`/data/leagues/${copy.league_id}/device-plan.json`, () => jsonResponse(COPY)],
    ]);
    const read = await createLeagueTree(league()).devicePlan(CAPTURE);
    expect(read.payload.league_id).toBe(copy.league_id);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      `/data/leagues/${copy.league_id}/device-plan.json`,
    ]);
  });

  it("refuses the capture's table where the tree's copy belongs", async () => {
    stubFetchByUrl([
      [
        `/data/leagues/${copy.league_id}/device-plan.json`,
        () => jsonResponse(envelope(captureTable())),
      ],
    ]);
    await expect(createLeagueTree(league()).devicePlan(CAPTURE)).rejects.toThrow(
      "not the expected shape",
    );
  });

  it("does not fall back once the page has stopped asking", async () => {
    const controller = new AbortController();
    const fetcher = stubFetchByUrl([
      [
        `/data/${TABLE_PATH}?v=${TABLE_SHA}`,
        () => {
          controller.abort();
          throw new DOMException("The operation was aborted.", "AbortError");
        },
      ],
      [`/data/leagues/${copy.league_id}/device-plan.json`, () => jsonResponse(COPY)],
    ]);
    await expect(
      createLeagueTree(league({ path: TABLE_PATH, sha256: TABLE_SHA })).devicePlan(CAPTURE, {
        signal: controller.signal,
      }),
    ).rejects.toThrow();
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([`/data/${TABLE_PATH}?v=${TABLE_SHA}`]);
  });

  it("does not give the copy a second deadline when the table's read ran out of time", async () => {
    // The copy is on the same site: a table that answers nothing within the deadline
    // fails the read there, instead of making the member wait a second deadline.
    const fetcher = vi.fn((url: string) =>
      url.includes("/data/device/")
        ? new Promise<Response>(() => {})
        : Promise.resolve(jsonResponse(COPY)),
    );
    vi.stubGlobal("fetch", fetcher);
    await expect(
      createLeagueTree(league({ path: TABLE_PATH, sha256: TABLE_SHA })).devicePlan(CAPTURE, {
        timeoutMs: 20,
      }),
    ).rejects.toMatchObject({ name: "TimeoutError" });
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([`/data/${TABLE_PATH}?v=${TABLE_SHA}`]);
  });
});

describe("the device-plan validator", () => {
  it("holds the tree's copy to its league and the capture's table to none", () => {
    expect(isDevicePlanDocument(copy)).toBe(true);
    expect(isDevicePlanDocument(captureTable())).toBe(true);
    const { league_id: _league, ...noLeague } = copy;
    expect(isDevicePlanDocument(noLeague)).toBe(false);
    expect(isDevicePlanDocument({ ...captureTable(), league_id: copy.league_id })).toBe(false);
  });

  it("holds the capture's table to its own fields", () => {
    const table = captureTable() as {
      players: Record<string, unknown>[];
      rules: Record<string, unknown>;
    };
    const { element_id: _element, ...noElement } = table.players[0] ?? {};
    expect(
      isDevicePlanDocument({ ...table, players: [noElement, ...table.players.slice(1)] }),
    ).toBe(false);
    const { chips: _chips, ...noChips } = table.rules;
    expect(isDevicePlanDocument({ ...table, rules: noChips })).toBe(false);
    expect(isDevicePlanDocument({ ...table, rules: { ...table.rules, transfers_cap: 2 } })).toBe(
      true,
    );
    expect(isDevicePlanDocument({ ...table, rules: { ...table.rules, transfers_cap: "2" } })).toBe(
      false,
    );
  });
});
