/**
 * The league loaders address the producer's tree by strategy and window: a three-week
 * pure-points request reads `advice/{id}/saf-puan/3.json` — in tests, the example of
 * exactly that document — and the index names the windows the producer wrote. The
 * scoreboard loader is the exception with no example: it returns the document as
 * published, or a named absence, never fiction.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../../fixtures/league";

import {
  LeagueDataError,
  LeagueDataMissing,
  loadEntryAdvice,
  loadEntryAdviceIndex,
  loadEntrySquad,
  loadLeagueMembers,
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

    expect(fetcher).toHaveBeenCalledWith("/data/league/scoreboard.json", {
      cache: "no-cache",
      signal: expect.any(AbortSignal),
    });
    expect(envelope.payload.season).toBe("2026-27");
  });

  it("raises LeagueDataMissing on a 404, the normal state before the first weekly run", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
    await expect(loadScoreboard()).rejects.toBeInstanceOf(LeagueDataMissing);
  });

  it.each(["<!doctype html><html></html>", ' \n<HTML lang="en"></HTML>'])(
    "raises LeagueDataMissing when a static host answers with the app shell: %s",
    async (body) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
      await expect(loadScoreboard()).rejects.toBeInstanceOf(LeagueDataMissing);
    },
  );

  it.each(["", " ", '{"contract_version":', "upstream unavailable"])(
    "keeps an unreadable publication distinct from a missing document: %s",
    async (body) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            new Response(body, { status: 200, headers: { "Content-Type": "application/json" } }),
          ),
      );
      const failure = loadScoreboard();
      await expect(failure).rejects.toBeInstanceOf(LeagueDataError);
      await expect(failure).rejects.not.toBeInstanceOf(LeagueDataMissing);
    },
  );

  it("does not hide a broken published member document behind development examples", async () => {
    vi.stubEnv("MODE", "development");
    vi.stubEnv("DEV", true);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"payload":')));
    const failure = loadLeagueMembers();
    await expect(failure).rejects.toBeInstanceOf(LeagueDataError);
    await expect(failure).rejects.not.toBeInstanceOf(LeagueDataMissing);
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
    expect(fetcher).toHaveBeenCalledWith("/data/league/members.json", {
      cache: "no-cache",
      signal: expect.any(AbortSignal),
    });
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

describe("published member document shapes", () => {
  function fromNetwork(value: unknown) {
    vi.stubEnv("MODE", "development");
    vi.stubEnv("DEV", true);
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(value)));
    vi.stubGlobal("fetch", fetcher);
    return fetcher;
  }

  it.each([null, { members: null }, { members: [null] }])(
    "rejects a malformed member list without development examples: %j",
    async (payload) => {
      const fetcher = fromNetwork({ ...mockLeagueMembersEnvelope, payload });
      const failure = loadLeagueMembers();
      await expect(failure).rejects.toBeInstanceOf(LeagueDataError);
      await expect(failure).rejects.not.toBeInstanceOf(LeagueDataMissing);
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );

  it.each(["entry", "starting_xi", "bench", "missing_fields"])(
    "rejects missing squad %s without development examples",
    async (field) => {
      const source = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
      const fetcher = fromNetwork({ ...source, payload: { ...source.payload, [field]: null } });
      const failure = loadEntrySquad(ENTRY);
      await expect(failure).rejects.toBeInstanceOf(LeagueDataError);
      await expect(failure).rejects.not.toBeInstanceOf(LeagueDataMissing);
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );

  it("refuses a well-shaped squad for another member", async () => {
    fromNetwork(mockEntrySquadEnvelopes[ENTRY]);
    await expect(loadEntrySquad(ENTRY + 1)).rejects.toBeInstanceOf(LeagueDataError);
  });

  it("refuses an object-valued display name instead of crashing the member list", async () => {
    const envelope = structuredClone(mockLeagueMembersEnvelope);
    const first = envelope.payload.members[0]!;
    fromNetwork({
      ...envelope,
      payload: { ...envelope.payload, members: [{ ...first, manager_name: {} }] },
    });
    await expect(loadLeagueMembers()).rejects.toBeInstanceOf(LeagueDataError);
  });

  it("refuses a malformed player instead of crashing the pitch", async () => {
    const envelope = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
    fromNetwork({ ...envelope, payload: { ...envelope.payload, starting_xi: [null] } });
    await expect(loadEntrySquad(ENTRY)).rejects.toBeInstanceOf(LeagueDataError);
  });

  it.each([ENTRY, 35249010])(
    "preserves valid partial or empty public squad %i",
    async (entryId) => {
      const envelope = mockEntrySquadEnvelopes[entryId]!;
      fromNetwork(envelope);
      await expect(loadEntrySquad(entryId)).resolves.toEqual(envelope);
    },
  );

  it("accepts a squad document from before the state fields, which carries none", async () => {
    const envelope = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
    const { chips: _chips, squad_basis: _basis, active_chip: _chip, ...older } = envelope.payload;
    const source = { ...envelope, payload: older };
    fromNetwork(source);
    await expect(loadEntrySquad(ENTRY)).resolves.toEqual(source);
  });

  it("accepts the squad state a producer without the chip history publishes", async () => {
    const envelope = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
    const unknown = { state: "unknown", gameweek: null, start_event: 1, stop_event: 19 };
    const source = {
      ...envelope,
      payload: {
        ...envelope.payload,
        chips_used: null,
        chips: {
          known: false,
          gameweek: 2,
          states: { wildcard: { first_half: unknown, second_half: null } },
        },
        squad_basis: "pre_free_hit_gw01",
        active_chip: "freehit",
      },
    };
    fromNetwork(source);
    await expect(loadEntrySquad(ENTRY)).resolves.toEqual(source);
  });

  const window = { state: "available", gameweek: null, start_event: 1, stop_event: 19 };
  it.each([
    ["chips", null],
    ["chips", { known: "yes", gameweek: 2, states: {} }],
    ["chips", { known: true, gameweek: null, states: {} }],
    ["chips", { known: true, gameweek: 2, states: [] }],
    ["chips", { known: true, gameweek: 2, states: { wildcard: null } }],
    ["chips", { known: true, gameweek: 2, states: { wildcard: { first_half: window } } }],
    [
      "chips",
      { known: true, gameweek: 2, states: { wildcard: { first_half: window, third: null } } },
    ],
    [
      "chips",
      {
        known: true,
        gameweek: 2,
        states: { wildcard: { first_half: { ...window, state: "maybe" }, second_half: null } },
      },
    ],
    [
      "chips",
      {
        known: true,
        gameweek: 2,
        states: { wildcard: { first_half: { ...window, stop_event: "19" }, second_half: null } },
      },
    ],
    ["squad_basis", null],
    ["squad_basis", 3],
    ["squad_basis", " "],
    ["active_chip", 7],
    ["active_chip", ""],
    ["active_chip", { name: "freehit" }],
  ])("refuses a malformed squad %s instead of reading it as absent: %j", async (field, value) => {
    const envelope = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
    const fetcher = fromNetwork({ ...envelope, payload: { ...envelope.payload, [field]: value } });
    const failure = loadEntrySquad(ENTRY);
    await expect(failure).rejects.toBeInstanceOf(LeagueDataError);
    await expect(failure).rejects.not.toBeInstanceOf(LeagueDataMissing);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
