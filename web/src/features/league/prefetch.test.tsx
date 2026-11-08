import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FIXTURES_QUERY } from "../fixtures/data";
import { stubTree } from "../../testSupport/league";
import { entryIdInAddress, prefetchMemberReads } from "./prefetch";
import { leagueKeys } from "./queries";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("prefetchMemberReads", () => {
  it("starts the member list, the squad, the advice index and the fixtures under the page's own keys", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("null", { headers: { "content-type": "application/json" } })),
    );
    const tree = stubTree({
      members: vi.fn(async () => ({ payload: { members: [] } }) as never),
      entrySquad: vi.fn(async () => ({ payload: {} }) as never),
      entryAdviceIndex: vi.fn(async () => ({ payload: {} }) as never),
    });
    const client = new QueryClient();

    prefetchMemberReads(client, tree, 35249001);
    await vi.waitFor(() => {
      expect(client.getQueryState(leagueKeys.members(tree.league.leagueId))?.status).toBe(
        "success",
      );
    });

    expect(tree.members).toHaveBeenCalledTimes(1);
    expect(tree.entrySquad).toHaveBeenCalledWith(35249001);
    expect(tree.entryAdviceIndex).toHaveBeenCalledWith(35249001);
    expect(
      client.getQueryState(leagueKeys.entrySquad(tree.league.leagueId, 35249001)),
    ).toBeDefined();
    expect(
      client.getQueryState(leagueKeys.adviceIndex(tree.league.leagueId, 35249001)),
    ).toBeDefined();
    expect(client.getQueryState(FIXTURES_QUERY.queryKey)).toBeDefined();
  });

  it("reads the member list alone on a league address without a member", () => {
    const tree = stubTree({
      members: vi.fn(async () => ({ payload: { members: [] } }) as never),
      entrySquad: vi.fn(),
      entryAdviceIndex: vi.fn(),
    });
    const client = new QueryClient();

    prefetchMemberReads(client, tree, null);

    expect(tree.members).toHaveBeenCalledTimes(1);
    expect(tree.entrySquad).not.toHaveBeenCalled();
    expect(tree.entryAdviceIndex).not.toHaveBeenCalled();
    expect(client.getQueryState(FIXTURES_QUERY.queryKey)).toBeUndefined();
  });

  it("reads the member from the address, and nothing from a malformed one", () => {
    expect(entryIdInAddress("35249001")).toBe(35249001);
    expect(entryIdInAddress(undefined)).toBeNull();
    expect(entryIdInAddress("abc")).toBeNull();
    expect(entryIdInAddress("0")).toBeNull();
  });
});
