import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BUNDLE_EXAMPLES,
  STANDINGS_EXAMPLES,
  exampleBundle,
  exampleMember,
  forwardedLive,
} from "../../../fixtures/forwarder";
import {
  createForwarderClient,
  entryBundle,
  FORWARDER_ROOT,
  type ForwarderClientOptions,
} from "./client";

afterEach(() => vi.unstubAllGlobals());

type Transport = NonNullable<ForwarderClientOptions["fetch"]>;

/** The forwarder's answer: JSON, marked, with the copy header a document carries. */
function forwarded(
  status: number,
  body: unknown,
  headers: Record<string, string> = status === 200 ? { "x-squadopt-fpl-cache": "miss" } : {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "x-squadopt-fpl": "1",
      ...headers,
    },
  });
}

/** The site's shell, which a route the forwarder does not answer falls through to. */
const SHELL = () =>
  new Response("<!doctype html><html><body><div id=root></div></body></html>", {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });

function clientAnswering(answer: () => Response | Promise<Response>) {
  const transport = vi.fn<Transport>(async () => answer());
  return { client: createForwarderClient({ fetch: transport }), transport };
}

describe("an answer the forwarder gave", () => {
  it("reads a standings page and asks the route on the site's own origin", async () => {
    const page = STANDINGS_EXAMPLES.first_page;
    const { client, transport } = clientAnswering(() => forwarded(200, page));
    expect(await client.standings(314, 1)).toEqual({ ok: true, document: page, copy: "miss" });
    expect(transport).toHaveBeenCalledTimes(1);
    const [url, init] = transport.mock.calls[0]!;
    expect(url).toBe(`${FORWARDER_ROOT}/standings/314?page=1`);
    expect(new Headers(init.headers).get("accept")).toBe("application/json");
  });

  it.each(Object.entries(BUNDLE_EXAMPLES))("reads the %s bundle", async (_, bundle) => {
    const { client, transport } = clientAnswering(() => forwarded(200, bundle));
    expect(await client.entryBundle(bundle.entry_id, bundle.gameweek)).toEqual({
      ok: true,
      document: bundle,
      copy: "miss",
    });
    expect(transport.mock.calls[0]![0]).toBe(
      `${FORWARDER_ROOT}/entry/${bundle.entry_id}/bundle?gw=${bundle.gameweek}`,
    );
  });

  it.each(["in_progress", "finished"] as const)("reads the %s live week", async (name) => {
    const week = forwardedLive(name, 6);
    const { client, transport } = clientAnswering(() => forwarded(200, week));
    expect(await client.liveWeek(6)).toEqual({ ok: true, document: week, copy: "miss" });
    expect(transport.mock.calls[0]![0]).toBe(`${FORWARDER_ROOT}/live/6`);
  });

  it("keeps the last good copy as the document, and says it is one", async () => {
    const week = forwardedLive("in_progress", 6);
    const { client } = clientAnswering(() =>
      forwarded(200, week, { "x-squadopt-fpl-cache": "last-good" }),
    );
    expect(await client.liveWeek(6)).toEqual({ ok: true, document: week, copy: "last-good" });
  });

  it("names no copy when the answer carries no word it knows", async () => {
    const week = forwardedLive("finished", 6);
    const { client } = clientAnswering(() => forwarded(200, week, { "x-squadopt-fpl-cache": "x" }));
    expect(await client.liveWeek(6)).toEqual({ ok: true, document: week, copy: null });
  });
});

describe("an answer that is not the forwarder's", () => {
  it("is the site's shell, at 200 or 404", async () => {
    for (const status of [200, 404]) {
      const { client } = clientAnswering(() =>
        status === 200 ? SHELL() : new Response("<html></html>", { status }),
      );
      expect(await client.liveWeek(6)).toEqual({ ok: false, reason: "not_forwarder" });
      expect(await client.entryBundle(101, 10)).toEqual({ ok: false, reason: "not_forwarder" });
      expect(await client.standings(314, 1)).toEqual({ ok: false, reason: "not_forwarder" });
    }
  });

  it("is JSON of the right shape without the mark", async () => {
    const { client } = clientAnswering(
      () =>
        new Response(JSON.stringify(forwardedLive("in_progress", 6)), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    expect(await client.liveWeek(6)).toEqual({ ok: false, reason: "not_forwarder" });
  });
});

describe("a marked answer this client does not read", () => {
  const week = forwardedLive("in_progress", 6);
  it.each([
    [
      "another contract version",
      () => forwarded(200, { ...week, contract_version: "week_live_v2" }),
    ],
    ["another gameweek than the one asked", () => forwarded(200, { ...week, gameweek: 5 })],
    [
      "member blocks, which the forwarder never sends",
      () => forwarded(200, { ...week, members: [] }),
    ],
    [
      "a position on an element, which the page resolves itself",
      () =>
        forwarded(200, {
          ...week,
          elements: week.elements.map((row) => ({ ...row, position: "GK" })),
        }),
    ],
    [
      "a body that is not JSON",
      () =>
        new Response("{", {
          status: 200,
          headers: { "content-type": "application/json", "x-squadopt-fpl": "1" },
        }),
    ],
    [
      "HTML under the mark",
      () =>
        new Response("<!doctype html>", {
          status: 200,
          headers: { "content-type": "text/html", "x-squadopt-fpl": "1" },
        }),
    ],
    ["the forwarder's own failure", () => forwarded(500, { error: "internal" })],
    ["a method refusal", () => forwarded(405, { error: "method_not_allowed" })],
    ["a 404 kind of another route", () => forwarded(404, { error: "entry_not_found" })],
    ["a 503 kind it does not name", () => forwarded(503, { error: "busy" })],
  ])("is unreadable for %s", async (_, answer) => {
    const { client } = clientAnswering(answer);
    expect(await client.liveWeek(6)).toEqual({ ok: false, reason: "unreadable" });
  });

  it("is unreadable for a standings page of another league or page", async () => {
    const page = STANDINGS_EXAMPLES.first_page;
    const { client } = clientAnswering(() => forwarded(200, page));
    expect(await client.standings(315, 1)).toEqual({ ok: false, reason: "unreadable" });
    expect(await client.standings(314, 2)).toEqual({ ok: false, reason: "unreadable" });
  });

  it("is unreadable for a bundle of another entry or table gameweek", async () => {
    const bundle = BUNDLE_EXAMPLES.late_joiner;
    const { client } = clientAnswering(() => forwarded(200, bundle));
    expect(await client.entryBundle(203, 10)).toEqual({ ok: false, reason: "unreadable" });
    expect(await client.entryBundle(202, 9)).toEqual({ ok: false, reason: "unreadable" });
  });
});

describe("the forwarder's refusals", () => {
  it.each([
    ["not_found", 404],
    ["head_to_head_league", 404],
    ["league_not_found", 404],
    ["page_not_found", 404],
    ["upstream_unavailable", 503],
  ] as const)("names %s for a league", async (error, status) => {
    const { client } = clientAnswering(() => forwarded(status, { error, league: 314 }));
    expect(await client.standings(314, 1)).toEqual({ ok: false, reason: error });
  });

  it.each([
    ["not_found", 404],
    ["entry_not_found", 404],
    ["upstream_unavailable", 503],
  ] as const)("names %s for an entry", async (error, status) => {
    const { client } = clientAnswering(() => forwarded(status, { error, entry: 101 }));
    expect(await client.entryBundle(101, 10)).toEqual({ ok: false, reason: error });
  });

  it.each([
    ["not_found", 404],
    ["upstream_unavailable", 503],
  ] as const)("names %s for a live week", async (error, status) => {
    const { client } = clientAnswering(() => forwarded(status, { error }));
    expect(await client.liveWeek(6)).toEqual({ ok: false, reason: error });
  });

  it("does not take a league's refusal from the bundle route", async () => {
    const { client } = clientAnswering(() => forwarded(404, { error: "head_to_head_league" }));
    expect(await client.entryBundle(101, 10)).toEqual({ ok: false, reason: "unreadable" });
  });

  it.each([
    ["a league id that is not a positive integer", (c: Client) => c.standings(0, 1)],
    ["a page past 20", (c: Client) => c.standings(314, 21)],
    ["a fractional page", (c: Client) => c.standings(314, 1.5)],
    ["a table gameweek before 2", (c: Client) => c.entryBundle(101, 1)],
    ["a table gameweek past 38", (c: Client) => c.entryBundle(101, 39)],
    ["an entry id past the safe integers", (c: Client) => c.entryBundle(2 ** 53, 10)],
    ["a live week of 0", (c: Client) => c.liveWeek(0)],
  ])("is not_found for %s, and asks nothing", async (_, read) => {
    const { client, transport } = clientAnswering(() => forwarded(200, {}));
    expect(await read(client)).toEqual({ ok: false, reason: "not_found" });
    expect(transport).not.toHaveBeenCalled();
  });
});

type Client = ReturnType<typeof createForwarderClient>;

describe("no answer", () => {
  it("is network when the request fails, and never throws", async () => {
    const failing = createForwarderClient({
      fetch: () => Promise.reject(new TypeError("Failed to fetch")),
    });
    expect(await failing.liveWeek(6)).toEqual({ ok: false, reason: "network" });
    const throwing = createForwarderClient({
      fetch: () => {
        throw new TypeError("Failed to parse URL");
      },
    });
    expect(await throwing.standings(314, 1)).toEqual({ ok: false, reason: "network" });
  });

  it("is network when the request runs out of time", async () => {
    const silent = createForwarderClient({
      fetch: (_, init) =>
        new Promise((_, reject) =>
          init.signal?.addEventListener("abort", () => reject(init.signal?.reason)),
        ),
    });
    expect(await silent.entryBundle(101, 10, { timeoutMs: 5 })).toEqual({
      ok: false,
      reason: "network",
    });
  });

  it("is aborted when the caller stops the read", async () => {
    const stop = new AbortController();
    const waiting = createForwarderClient({
      fetch: (_, init) =>
        new Promise((_, reject) =>
          init.signal?.addEventListener("abort", () => reject(init.signal?.reason)),
        ),
    });
    const read = waiting.liveWeek(6, { signal: stop.signal });
    stop.abort();
    expect(await read).toEqual({ ok: false, reason: "aborted" });
  });
});

it("the site's own client reads through the browser's fetch", async () => {
  const bundle = exampleBundle(35249001, 2, exampleMember(35249001, 2));
  const fetched = vi.fn(async () => forwarded(200, bundle));
  vi.stubGlobal("fetch", fetched);
  expect(await entryBundle(35249001, 2)).toEqual({ ok: true, document: bundle, copy: "miss" });
  expect(fetched).toHaveBeenCalledWith(
    "/api/v1/fpl/entry/35249001/bundle?gw=2",
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  );
});

describe("a bundle's identities", () => {
  const bundle = BUNDLE_EXAMPLES.free_hit_walk_back;
  const read = async (document: unknown) =>
    clientAnswering(() => forwarded(200, document)).client.entryBundle(101, 10);

  it.each([
    ["a transfer of another entry", { transfers: [{ ...bundle.transfers[0]!, entry: 102 }] }],
    ["an entry naming another id", { entry: { ...bundle.entry, id: 102 } }],
    ["picks out of week order", { picks: [...bundle.picks].reverse() }],
    [
      "picks of the table gameweek itself",
      {
        picks: [
          ...bundle.picks,
          { ...bundle.picks[2]!, entry_history: { ...bundle.picks[2]!.entry_history, event: 10 } },
        ],
      },
    ],
    [
      "a current week of another entry",
      { current_week: { ...bundle.current_week!, entry_id: 102 } },
    ],
    [
      "a current week before the held week",
      { current_week: { ...bundle.current_week!, gameweek: 8 } },
    ],
    [
      "a current week with an unknown chip",
      { current_week: { ...bundle.current_week!, active_chip: "manager" } },
    ],
    ["a source time that is no instant", { source_time: "2026-02-31T00:00:00Z" }],
    [
      "a bank that is not a number",
      { history: { ...bundle.history, current: [{ ...bundle.history.current[0]!, bank: "5" }] } },
    ],
  ])("refuses %s", async (_, change) => {
    expect(await read({ ...bundle, ...change })).toEqual({ ok: false, reason: "unreadable" });
  });

  it("reads a bundle with no current week", async () => {
    expect(await read({ ...bundle, current_week: null })).toMatchObject({ ok: true });
  });
});

describe("a standings page's rows", () => {
  const page = STANDINGS_EXAMPLES.first_page;
  const read = async (document: unknown) =>
    clientAnswering(() => forwarded(200, document)).client.standings(314, 1);

  it.each([
    ["an entry twice", { results: [page.results[0]!, page.results[0]!] }],
    ["a head-to-head league", { league: { ...page.league, scoring: "h2h" } }],
    ["a rank_sort of 0", { results: [{ ...page.results[0]!, rank_sort: 0 }] }],
    ["a missing has_next", { has_next: undefined }],
  ])("refuses %s", async (_, change) => {
    expect(await read({ ...page, ...change })).toEqual({ ok: false, reason: "unreadable" });
  });

  it("reads a league with no name and no update time", async () => {
    expect(
      await read({ ...page, league: { ...page.league, name: null }, last_updated_data: null }),
    ).toMatchObject({ ok: true });
  });
});
