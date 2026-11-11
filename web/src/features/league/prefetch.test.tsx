import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FIXTURES_QUERY } from "../fixtures/data";
import { stubTree } from "../../testSupport/league";
import { LeagueDataMissing } from "./dataErrors";
import { entryIdInAddress, prefetchMemberReads } from "./prefetch";
import { leagueKeys } from "./queries";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("prefetchMemberReads", () => {
  it("starts the member's documents and the fixtures under the page's own keys", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("null", { headers: { "content-type": "application/json" } })),
    );
    const tree = stubTree({
      members: vi.fn(async () => ({ payload: { members: [] } }) as never),
      entrySquad: vi.fn(async () => ({ payload: {} }) as never),
      entryAdviceIndex: vi.fn(async () => ({ payload: {} }) as never),
      scoreboard: vi.fn(async () => ({ payload: {} }) as never),
      raw: vi.fn(async () => {
        throw new LeagueDataMissing("history");
      }),
    });
    const client = new QueryClient();

    prefetchMemberReads(client, tree, 35249001, [35249002, null, 35249002]);
    await vi.waitFor(() => {
      expect(client.getQueryState(leagueKeys.members(tree.league.leagueId))?.status).toBe(
        "success",
      );
    });

    expect(tree.members).toHaveBeenCalledTimes(1);
    expect(tree.entrySquad).toHaveBeenCalledWith(35249001);
    expect(tree.entryAdviceIndex).toHaveBeenCalledWith(35249001);
    expect(tree.scoreboard).toHaveBeenCalledTimes(1);
    expect(tree.raw).toHaveBeenCalledWith("history/35249001.json", expect.anything());
    // The rival the address names, once however often it is named.
    expect(tree.entrySquad).toHaveBeenCalledWith(35249002);
    expect(tree.entrySquad).toHaveBeenCalledTimes(2);
    expect(client.getQueryState(leagueKeys.scoreboard(tree.league.leagueId))).toBeDefined();
    expect(
      client.getQueryState(leagueKeys.suggestionHistory(tree.league.leagueId, 35249001)),
    ).toBeDefined();
    expect(
      client.getQueryState(leagueKeys.entrySquad(tree.league.leagueId, 35249001)),
    ).toBeDefined();
    expect(
      client.getQueryState(leagueKeys.adviceIndex(tree.league.leagueId, 35249001)),
    ).toBeDefined();
    expect(client.getQueryState(FIXTURES_QUERY.queryKey)).toBeDefined();
  });

  it("starts LIVE's own documents alone: no scoreboard, no history and no rival's squad", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("null", { headers: { "content-type": "application/json" } })),
    );
    const tree = stubTree({
      members: vi.fn(async () => ({ payload: { members: [] } }) as never),
      entrySquad: vi.fn(async () => ({ payload: {} }) as never),
      entryAdviceIndex: vi.fn(async () => ({ payload: {} }) as never),
      scoreboard: vi.fn(),
      raw: vi.fn(),
    });
    const client = new QueryClient();

    prefetchMemberReads(client, tree, 35249001, [35249002], "live");
    await vi.waitFor(() => {
      expect(client.getQueryState(leagueKeys.members(tree.league.leagueId))?.status).toBe(
        "success",
      );
    });

    expect(tree.entrySquad).toHaveBeenCalledTimes(1);
    expect(tree.entrySquad).toHaveBeenCalledWith(35249001);
    expect(tree.entryAdviceIndex).toHaveBeenCalledWith(35249001);
    expect(tree.scoreboard).not.toHaveBeenCalled();
    expect(tree.raw).not.toHaveBeenCalled();
    expect(client.getQueryState(FIXTURES_QUERY.queryKey)).toBeDefined();
  });

  it("starts no index for LIVE in a league read through the forwarder, whose rival comes from its table", () => {
    const tree = stubTree({
      members: vi.fn(async () => ({ payload: { members: [] } }) as never),
      entrySquad: vi.fn(async () => ({ payload: {} }) as never),
      entryAdviceIndex: vi.fn(async () => ({ payload: {} }) as never),
    });
    const client = new QueryClient();
    prefetchMemberReads(client, tree, 35249001, [], "live", true);
    expect(tree.entrySquad).toHaveBeenCalledWith(35249001);
    expect(tree.entryAdviceIndex).not.toHaveBeenCalled();
    client.clear();
  });

  it("reads the member list alone on a league address without a member", () => {
    const tree = stubTree({
      members: vi.fn(async () => ({ payload: { members: [] } }) as never),
      entrySquad: vi.fn(),
      entryAdviceIndex: vi.fn(),
      scoreboard: vi.fn(),
    });
    const client = new QueryClient();

    prefetchMemberReads(client, tree, null, [35249002]);

    expect(tree.members).toHaveBeenCalledTimes(1);
    expect(tree.entrySquad).not.toHaveBeenCalled();
    expect(tree.entryAdviceIndex).not.toHaveBeenCalled();
    expect(tree.scoreboard).not.toHaveBeenCalled();
    expect(client.getQueryState(FIXTURES_QUERY.queryKey)).toBeUndefined();
  });

  it("reads the member from the address, and nothing from a malformed one", () => {
    expect(entryIdInAddress("35249001")).toBe(35249001);
    expect(entryIdInAddress(undefined)).toBeNull();
    expect(entryIdInAddress(null)).toBeNull();
    expect(entryIdInAddress("abc")).toBeNull();
    expect(entryIdInAddress("0")).toBeNull();
  });
});
