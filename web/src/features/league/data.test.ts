/**
 * The league loaders address the producer's tree by strategy and window: a three-week
 * pure-points request reads `advice/{id}/saf-puan/3.json` — in tests, the example of
 * exactly that document — and the index names the windows the producer wrote. The
 * scoreboard loader is the exception with no example: it returns the document as
 * published, or a named absence, never fiction.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  LeagueDataError,
  LeagueDataMissing,
  loadEntryAdvice,
  loadEntryAdviceIndex,
  loadScoreboard,
  lookupPublishedLeague,
} from "./data";

const ENTRY = 35249001;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("league advice loaders", () => {
  it.each([1, 3, 5] as const)("loads the pure-points document for window %i", async (window) => {
    const envelope = await loadEntryAdvice(ENTRY, "saf-puan", window);
    expect(envelope.contract_version).toBe("provisional_league_ui_v1");
    expect(envelope.payload).toMatchObject({ entry_id: ENTRY, mode: "saf-puan", window });
    if (window === 1) {
      expect(envelope.payload.plan_weeks).toBeUndefined();
    } else {
      expect(envelope.payload.plan_weeks).toHaveLength(window);
      expect(envelope.payload.stated_limits?.length).toBeGreaterThan(0);
    }
  });

  it("lists the windows the producer wrote per strategy", async () => {
    const index = (await loadEntryAdviceIndex(ENTRY)).payload;
    expect(index.windows).toEqual({ "saf-puan": [1, 3, 5], "ortak-koru": [1], "fark-yarat": [1] });
    expect(index.window).toBe(1);
  });
});

const published = {
  contract_version: "provisional_league_ui_v1",
  generated_at_utc: "2026-09-07T13:20:00Z",
  source_kind: "live",
  payload: { season: "2026-27", gameweeks: [], cumulative: { through_gameweek: null } },
};

describe("loadScoreboard", () => {
  it("reads data/league/scoreboard.json without caching and returns its envelope", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(published)));
    vi.stubGlobal("fetch", fetcher);

    const envelope = await loadScoreboard();

    expect(fetcher).toHaveBeenCalledWith("/data/league/scoreboard.json", { cache: "no-cache" });
    expect(envelope.payload.season).toBe("2026-27");
  });

  it("raises LeagueDataMissing on a 404, the normal state before the first weekly run", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
    await expect(loadScoreboard()).rejects.toBeInstanceOf(LeagueDataMissing);
  });

  it("raises LeagueDataMissing when a static host answers with the app shell", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<!doctype html><html></html>", { status: 200 })),
    );
    await expect(loadScoreboard()).rejects.toBeInstanceOf(LeagueDataMissing);
  });

  it("refuses another contract version as an error, not as an absence", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ ...published, contract_version: "ui_view_v1" })),
        ),
    );
    const failure = loadScoreboard();
    await expect(failure).rejects.toBeInstanceOf(LeagueDataError);
    await expect(failure).rejects.not.toBeInstanceOf(LeagueDataMissing);
  });

  it("does not fall back to an example: there is no example scoreboard", async () => {
    // Other league loaders serve fixtures in test mode; a scoreboard has none, so the
    // missing state is what tests and the development server both see.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
    await expect(loadScoreboard()).rejects.toThrow("No published league document");
  });
});

const publishedMembers = {
  contract_version: "provisional_league_ui_v1",
  generated_at_utc: "2026-09-09T06:00:00Z",
  source_kind: "live",
  payload: {
    league_id: 352490,
    league_name: "Published league",
    season: "2026-27",
    gameweek: 4,
    public_after_deadline: true,
    scored_gameweek: 3,
    members: [],
  },
};

describe("published league lookup", () => {
  it("uses the fixed publication URL and treats an empty connected league as connected", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(publishedMembers)));
    vi.stubGlobal("fetch", fetcher);
    await expect(lookupPublishedLeague(352490)).resolves.toBe("connected");
    expect(fetcher).toHaveBeenCalledWith("/data/league/members.json", { cache: "no-cache" });
  });

  it("rejects any other ID without requesting a document or upstream API", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    await expect(lookupPublishedLeague(123)).resolves.toBe("unsupported");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each(["test", "development"])("never falls back to an example in %s", async (mode) => {
    vi.stubEnv("MODE", mode);
    vi.stubEnv("DEV", true);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
    await expect(lookupPublishedLeague(352490)).rejects.toBeInstanceOf(LeagueDataMissing);
  });

  it.each([0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1])(
    "refuses invalid ID %s without a fetch",
    async (id) => {
      const fetcher = vi.fn();
      vi.stubGlobal("fetch", fetcher);
      await expect(lookupPublishedLeague(id)).rejects.toBeInstanceOf(LeagueDataError);
      expect(fetcher).not.toHaveBeenCalled();
    },
  );

  it.each([
    { ...publishedMembers, source_kind: "example" },
    { ...publishedMembers, contract_version: "other" },
    { ...publishedMembers, payload: null },
    { ...publishedMembers, payload: { ...publishedMembers.payload, public_after_deadline: false } },
    { ...publishedMembers, payload: { ...publishedMembers.payload, league_id: "352490" } },
    { ...publishedMembers, payload: { ...publishedMembers.payload, league_id: 123 } },
    { ...publishedMembers, payload: { ...publishedMembers.payload, members: [null] } },
  ])(
    "does not classify an incompatible or invalid publication as a league result",
    async (value) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(value))));
      await expect(lookupPublishedLeague(352490)).rejects.toBeInstanceOf(LeagueDataError);
    },
  );

  it("keeps transport failure distinct from missing publication", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));
    const request = lookupPublishedLeague(352490);
    await expect(request).rejects.toBeInstanceOf(LeagueDataError);
    await expect(request).rejects.not.toBeInstanceOf(LeagueDataMissing);
  });
});
