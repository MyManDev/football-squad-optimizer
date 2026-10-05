import { afterEach, describe, expect, it, vi } from "vitest";

import { LeagueDataError, LeagueDataMissing } from "./dataErrors";
import { fetchPublishedJson } from "./publishedJson";

/** One answer for every address, kept so the test can see whether its body was read. */
function answer(response: Response): Response {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response),
  );
  return response;
}

const PAGES_NOT_FOUND = "<!doctype html><p>No document is published at this address.</p>";

afterEach(() => vi.unstubAllGlobals());

describe("fetchPublishedJson", () => {
  it("reads a 404's body before saying the document is missing", async () => {
    const response = answer(new Response(PAGES_NOT_FOUND, { status: 404 }));
    await expect(fetchPublishedJson("/data/", "leagues.json")).rejects.toBeInstanceOf(
      LeagueDataMissing,
    );
    expect(response.bodyUsed).toBe(true);
  });

  it("reads any other refusal's body before reporting it", async () => {
    const response = answer(new Response("<html>bad gateway</html>", { status: 502 }));
    await expect(fetchPublishedJson("/data/", "league/members.json")).rejects.toBeInstanceOf(
      LeagueDataError,
    );
    expect(response.bodyUsed).toBe(true);
  });

  it("reads the application shell as a missing document", async () => {
    answer(new Response("<!doctype html><title>shell</title>", { status: 200 }));
    await expect(fetchPublishedJson("/data/", "leagues.json")).rejects.toBeInstanceOf(
      LeagueDataMissing,
    );
  });

  it("refuses a published document that is not JSON", async () => {
    answer(new Response("{ not json", { status: 200 }));
    await expect(fetchPublishedJson("/data/", "league/members.json")).rejects.toThrow(
      "The published league document at league/members.json is not valid JSON.",
    );
  });

  it("returns the parsed document", async () => {
    const fetcher = vi.fn(async () => new Response('{"a":1}', { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(fetchPublishedJson("/data/", "leagues/1/members.json")).resolves.toEqual({
      a: 1,
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/data/leagues/1/members.json",
      expect.objectContaining({ cache: "no-cache" }),
    );
  });
});
