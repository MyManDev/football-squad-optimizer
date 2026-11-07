/**
 * The forwarded league's tree: the member list from the standings pages read, each member's
 * squad from their bundle bound to the capture's table, and a device-menu index for each,
 * all in the shapes the published trees are held to. Advice, the scoreboard and the history
 * stay unpublished.
 */

import { describe, expect, it, vi } from "vitest";

import deviceInstances from "../../../fixtures/device-plan/instances.json";
import {
  bundleHolding,
  fixtureCaptureTable,
  STANDINGS_EXAMPLES,
} from "../../../fixtures/forwarder";
import { LeagueDataError, LeagueDataMissing } from "../data";
import type { PublishedLeague } from "../directory";
import type { ForwarderResult } from "../forwarder/client";
import type { FplEntryBundle, FplLeagueStandings } from "../forwarder/documents";
import { assertAdviceIndex, assertMembers } from "../publicationShape";
import {
  defaultRivalOf,
  forwardedTree,
  standingsMembers,
  type ForwardedSources,
} from "./forwardedTree";

const CAPTURE = "fpl-live-20261016T060000Z-0123456789ab";
const TABLE = fixtureCaptureTable(CAPTURE);
const member = deviceInstances.members[2]!;
const ENTRY = member.entry_id;
const RIVAL = 777001;
const FIFTEEN = [101, 111, 114, 115, 116, 131, 132, 136, 139, 154, 155, 105, 123, 148, 156];
const WORTH = Object.values(member.entry.sell_tenths).reduce((sum, price) => sum + price, 0);

function bundleFor(entryId: number): FplEntryBundle {
  return bundleHolding(entryId, TABLE.gameweek, FIFTEEN, {
    bank: member.entry.bank_tenths,
    value: member.entry.bank_tenths + WORTH,
    captain: 132,
    vice: 139,
  });
}

const LEAGUE: PublishedLeague = {
  leagueId: 314,
  leagueName: "Synthetic League",
  season: TABLE.season,
  gameweek: TABLE.gameweek,
  path: "",
  devicePlan: { path: `device/${CAPTURE}/device-plan.json`, sha256: "0".repeat(64) },
};

const TABLE_ENVELOPE = {
  contract_version: "provisional_league_ui_v1" as const,
  generated_at_utc: "2026-10-16T08:00:00Z",
  source_kind: "live" as const,
  payload: TABLE,
};

/** Page 1 of the example league with the fixture member ranked second and a rival above. */
function page(): FplLeagueStandings {
  const example = structuredClone(STANDINGS_EXAMPLES.first_page) as FplLeagueStandings;
  example.results = [
    { ...example.results[0]!, entry: RIVAL, rank: 1, rank_sort: 1, last_rank: 2 },
    { ...example.results[1]!, entry: ENTRY, rank: 2, rank_sort: 2, last_rank: 1 },
    ...example.results.slice(2),
    { ...example.results[0]!, entry: 5099, rank: 99, rank_sort: 99, last_rank: null },
  ];
  return example;
}

function ok<T>(document: T): ForwarderResult<T> {
  return { ok: true, document, copy: "hit" };
}

function sources(overrides: Partial<ForwardedSources> = {}): ForwardedSources {
  return {
    standings: vi.fn(async () => ok(page())),
    entryBundle: vi.fn(async (entry: number) => ok(bundleFor(entry))),
    ...overrides,
  };
}

describe("the member list", () => {
  it("is the standings rows in the published shape, with the movement the standings state", () => {
    const members = standingsMembers([page()]);
    expect(assertMembers).toBeTypeOf("function");
    expect(members[0]).toMatchObject({
      member_kind: "human",
      entry_id: RIVAL,
      rank: 1,
      movement: "up",
      movement_places: 1,
      transfer_cost: null,
      data_quality: "partial",
    });
    expect(members[1]).toMatchObject({ entry_id: ENTRY, movement: "down", movement_places: 1 });
    const newcomer = members.find((row) => row.entry_id === 5099);
    expect(newcomer).toMatchObject({ movement: "new", movement_places: null });
  });

  it("reads page 1 once where the page handed none, and uses the pages it was handed", async () => {
    const reads = sources();
    const tree = forwardedTree({
      league: LEAGUE,
      table: TABLE_ENVELOPE,
      fixtures: null,
      sources: reads,
    });
    const first = await tree.members();
    const second = await tree.members();
    expect(reads.standings).toHaveBeenCalledTimes(1);
    expect(first.payload.league_id).toBe(314);
    expect(first.payload.members.map((row) => row.entry_id)).toEqual(
      second.payload.members.map((row) => row.entry_id),
    );
    const handed = sources();
    const given = forwardedTree({
      league: LEAGUE,
      table: TABLE_ENVELOPE,
      fixtures: null,
      pages: [page()],
      sources: handed,
    });
    await given.members();
    expect(handed.standings).not.toHaveBeenCalled();
  });

  it("is not published for an entry opened on its own", async () => {
    const tree = forwardedTree({
      league: { ...LEAGUE, leagueId: 0, leagueName: "" },
      table: TABLE_ENVELOPE,
      fixtures: null,
      sources: sources(),
    });
    await expect(tree.members()).rejects.toBeInstanceOf(LeagueDataMissing);
  });
});

describe("a member's squad", () => {
  it("is built from a handed bundle without asking the forwarder, and from the forwarder once otherwise", async () => {
    const reads = sources();
    const tree = forwardedTree({
      league: LEAGUE,
      table: TABLE_ENVELOPE,
      fixtures: null,
      pages: [page()],
      bundles: [bundleFor(ENTRY)],
      sources: reads,
    });
    const own = await tree.entrySquad(ENTRY);
    expect(reads.entryBundle).not.toHaveBeenCalled();
    expect(own.payload.entry).toMatchObject({ entry_id: ENTRY, rank: 2, total_points: 593 });
    expect(own.payload.device_plan?.held).toHaveLength(15);
    expect(own.payload.source_snapshot_id).toBe(CAPTURE);
    const rival = await tree.entrySquad(RIVAL);
    await tree.entrySquad(RIVAL);
    expect(reads.entryBundle).toHaveBeenCalledTimes(1);
    expect(reads.entryBundle).toHaveBeenCalledWith(RIVAL, TABLE.gameweek);
    expect(rival.payload.entry.rank).toBe(1);
  });

  it("reads as not published for a team FPL does not have, and as an error the forwarder could not answer", async () => {
    const refusing = sources({
      entryBundle: vi.fn(async (entry: number) =>
        entry === RIVAL
          ? ({ ok: false, reason: "entry_not_found" } as const)
          : ({ ok: false, reason: "upstream_unavailable" } as const),
      ),
    });
    const tree = forwardedTree({
      league: LEAGUE,
      table: TABLE_ENVELOPE,
      fixtures: null,
      sources: refusing,
    });
    await expect(tree.entrySquad(RIVAL)).rejects.toBeInstanceOf(LeagueDataMissing);
    await expect(tree.entrySquad(ENTRY)).rejects.toBeInstanceOf(LeagueDataError);
  });
});

describe("a member's index", () => {
  it("is a device menu the published shape accepts, naming the other members as rivals and the one above first", async () => {
    const tree = forwardedTree({
      league: LEAGUE,
      table: TABLE_ENVELOPE,
      fixtures: null,
      pages: [page()],
      sources: sources(),
    });
    const index = await tree.entryAdviceIndex(ENTRY);
    expect(() => assertAdviceIndex(index, ENTRY)).not.toThrow();
    expect(index.payload).toMatchObject({
      menu: "device",
      source_snapshot_id: CAPTURE,
      strategies: ["saf-puan", "ortak-koru", "fark-yarat"],
      default_rival_entry_id: RIVAL,
      computed: [],
      chips: { available: false, reason: "on_device" },
    });
    expect(index.payload.rival_entry_ids).toContain(RIVAL);
    expect(index.payload.rival_entry_ids).not.toContain(ENTRY);
    expect(index.payload.chip_states?.gameweek).toBe(TABLE.gameweek);
  });

  it("names no rival for an entry on its own", async () => {
    const tree = forwardedTree({
      league: { ...LEAGUE, leagueId: 0, leagueName: "" },
      table: TABLE_ENVELOPE,
      fixtures: null,
      sources: sources(),
    });
    const index = await tree.entryAdviceIndex(ENTRY);
    expect(index.payload).toMatchObject({
      league_id: 0,
      rival_entry_ids: [],
      default_rival_entry_id: null,
    });
  });

  it("picks the member below when nobody is above", () => {
    const members = standingsMembers([page()]);
    expect(defaultRivalOf(members, RIVAL)).toBe(ENTRY);
    expect(defaultRivalOf(members, 999)).toBeNull();
  });
});

describe("what stays unpublished", () => {
  it("is every advice document, the scoreboard and the history", async () => {
    const tree = forwardedTree({
      league: LEAGUE,
      table: TABLE_ENVELOPE,
      fixtures: null,
      sources: sources(),
    });
    await expect(tree.entryAdvice(ENTRY, "saf-puan", 1)).rejects.toBeInstanceOf(LeagueDataMissing);
    await expect(tree.scoreboard()).rejects.toBeInstanceOf(LeagueDataMissing);
    await expect(tree.raw("history/1.json")).rejects.toBeInstanceOf(LeagueDataMissing);
    await expect(tree.devicePlan("other")).rejects.toBeInstanceOf(LeagueDataMissing);
    expect((await tree.devicePlan(CAPTURE)).payload.source_snapshot_id).toBe(CAPTURE);
  });
});
