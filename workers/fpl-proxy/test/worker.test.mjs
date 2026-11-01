// The FPL forwarder's fetch handler, run with node --test against a fake FPL, a fake site, an
// in-memory cache and a clock the test moves. No Cloudflare account and no network.
//
// What a reader of these answers relies on is pinned here: the three routes answer only their
// trimmed documents, every answer is JSON with the marker header, nothing of FPL's own JSON
// leaks, each copy lives as long as ADR 0012 says, and when FPL refuses or fails the last good
// copy comes back with its original source time.

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describe, it } from "node:test";

import entryPoint from "../src/index.js";
import {
  BUNDLE_CONTRACT,
  CACHE_HEADER,
  LAST_GOOD_EXTRA_SECONDS,
  LIVE_CONTRACT,
  MARKER_HEADER,
  MARKER_VALUE,
  NOT_FOUND_TTL_SECONDS,
  SCHEDULE_CACHE_KEY,
  SCHEDULE_TTL_SECONDS,
  SCHEDULE_URL,
  STANDINGS_CONTRACT,
  STANDINGS_TTL_SECONDS,
  USER_AGENT,
  cacheKeys,
  upstreamPaths,
} from "../src/proxy.js";
import { createWorker } from "../src/worker.js";
import { contractFile, problems } from "./schema.mjs";
import {
  LATE,
  MARKER,
  NOW_MS,
  OPENER,
  SITE,
  bundleWorld,
  deadlineMs,
  fakeFetch,
  fixturesJson,
  fpl,
  liveWorld,
  memoryCache,
  standingsPage,
  status,
  testClock,
} from "./support.mjs";

const REPOSITORY = new URL("../../../", import.meta.url);

/** One Worker over one fake world, with its cache, clock, calls and log lines. */
function harness(answers, { start = NOW_MS } = {}) {
  const clock = testClock(start);
  const cache = memoryCache(clock);
  const upstream = fakeFetch(answers);
  const lines = [];
  const worker = createWorker({
    fetch: upstream.fetchImpl,
    cache,
    now: clock.now,
    log: (event, fields) => lines.push({ event, ...fields }),
  });
  const get = async (path, init = {}) => {
    const response = await worker.fetch(new Request(`${SITE}${path}`, init));
    const text = await response.text();
    return { response, text, body: text === "" ? null : JSON.parse(text) };
  };
  return { clock, cache, upstream, lines, worker, get };
}

function assertJsonAndMarked(response, label) {
  assert.match(response.headers.get("content-type"), /^application\/json\b/, label);
  assert.equal(response.headers.get(MARKER_HEADER), MARKER_VALUE, label);
  assert.equal(response.headers.get("cache-control"), "no-store", label);
}

const standingsWorld = () => ({
  [fpl(upstreamPaths.classicStandings(314, 1))]: standingsPage({ page: 1, hasNext: true }),
  [fpl(upstreamPaths.classicStandings(314, 2))]: standingsPage({ page: 2, rows: 2 }),
});

const fplCalls = (calls) => calls.filter((call) => call.url.startsWith("https://fantasy."));

describe("every answer", () => {
  it("is JSON with the marker header, refusals and errors included", async () => {
    const world = { ...standingsWorld(), ...bundleWorld(), ...liveWorld() };
    const { get } = harness(world);
    const paths = [
      "/api/v1/fpl/standings/314?page=1",
      "/api/v1/fpl/entry/101/bundle?gw=10",
      "/api/v1/fpl/live/9",
      "/api/v1/fpl/nothing-here",
      "/api/v1/fpl/standings/abc?page=1",
      "/api/v1/fpl/standings/314?page=21",
      "/api/v1/fpl/live/12",
    ];
    for (const path of paths) {
      const { response, body } = await get(path);
      assertJsonAndMarked(response, path);
      assert.equal(typeof body, "object", path);
    }
    const { response, body } = await get("/api/v1/fpl/live/9", { method: "POST" });
    assert.equal(response.status, 405);
    assert.equal(response.headers.get("allow"), "GET");
    assertJsonAndMarked(response, "POST");
    assert.equal(body.error, "method_not_allowed");
  });

  it("refuses a path outside the allowlist, a non-numeric id and page 21 without asking anyone", async () => {
    const { get, upstream } = harness({});
    for (const path of [
      "/api/v1/fpl/bootstrap-static/",
      "/api/v1/fpl/entry/101/history/",
      "/api/v1/fpl/standings/abc?page=1",
      "/api/v1/fpl/entry/0/bundle?gw=10",
      "/api/v1/fpl/entry/-3/bundle?gw=10",
      "/api/v1/fpl/standings/314?page=21",
      "/api/v1/fpl/live/0",
    ]) {
      const { response, body } = await get(path);
      assert.equal(response.status, 404, path);
      assert.equal(body.error, "not_found", path);
    }
    assert.equal(upstream.calls.length, 0);
  });

  it("answers an unexpected failure with a JSON 500 that still carries the marker", async () => {
    const worker = createWorker({ fetch: async () => Response.json({}), log: () => {} });
    const response = await worker.fetch({ method: "GET", url: "not a url" });
    assert.equal(response.status, 500);
    assertJsonAndMarked(response, "500");
    assert.deepEqual(await response.json(), { error: "internal" });
  });
});

describe("standings", () => {
  it("answers fpl_league_standings_v1 exactly as the committed examples show", async () => {
    const examples = await contractFile("fpl_league_standings_v1.examples.json");
    const schema = await contractFile("fpl_league_standings_v1.schema.json");
    const { get } = harness(standingsWorld());
    for (const [name, page] of [
      ["first_page", 1],
      ["last_page", 2],
    ]) {
      const { body, text } = await get(`/api/v1/fpl/standings/314?page=${page}`);
      assert.deepEqual(problems(schema, body), [], name);
      assert.deepEqual(body, examples[name], name);
      assert.ok(!text.includes(MARKER), name);
    }
  });

  it("answers fpl_league_standings_v1, asks FPL once, then serves its copy for 10 minutes", async () => {
    const { get, upstream, cache, clock } = harness(standingsWorld());
    const first = await get("/api/v1/fpl/standings/314?page=1");
    assert.equal(first.response.status, 200);
    assert.equal(first.response.headers.get(CACHE_HEADER), "miss");
    assert.equal(first.body.contract_version, STANDINGS_CONTRACT);
    assert.deepEqual(
      problems(await contractFile("fpl_league_standings_v1.schema.json"), first.body),
      [],
    );
    assert.ok(!first.text.includes(MARKER));

    const keys = cacheKeys({ kind: "standings", league: 314, page: 1 });
    assert.equal(cache.stored.get(keys.fresh).maxAge, STANDINGS_TTL_SECONDS);
    assert.equal(
      cache.stored.get(keys.lastGood).maxAge,
      STANDINGS_TTL_SECONDS + LAST_GOOD_EXTRA_SECONDS,
    );

    clock.advance((STANDINGS_TTL_SECONDS - 1) * 1000);
    const again = await get("/api/v1/fpl/standings/314?page=1");
    assert.equal(again.response.headers.get(CACHE_HEADER), "hit");
    assert.equal(again.text, first.text);
    assert.equal(upstream.calls.length, 1);

    clock.advance(1000);
    await get("/api/v1/fpl/standings/314?page=1");
    assert.equal(upstream.calls.length, 2);
  });

  it("asks FPL with the capture's user agent and with Cloudflare's own cache out of the way", async () => {
    const { get, upstream } = harness(standingsWorld());
    await get("/api/v1/fpl/standings/314?page=2");
    assert.equal(upstream.calls.length, 1);
    const [{ url, init }] = upstream.calls;
    assert.equal(url, fpl("leagues-classic/314/standings/?page_standings=2"));
    assert.equal(new Headers(init.headers).get("user-agent"), USER_AGENT);
    assert.deepEqual(init.cf, { cacheTtl: 0 });
    assert.ok(init.signal instanceof AbortSignal);
  });

  it("names a head-to-head league in its refusal, as the capture asks it", async () => {
    const { get, upstream, cache } = harness({
      [fpl(upstreamPaths.classicStandings(77, 1))]: status(404),
      [fpl(upstreamPaths.headToHeadStandings(77))]: { league: { id: 77 }, standings: {} },
    });
    const { response, body } = await get("/api/v1/fpl/standings/77?page=1");
    assert.equal(response.status, 404);
    assertJsonAndMarked(response, "h2h");
    assert.equal(body.error, "head_to_head_league");
    assert.equal(body.league, 77);
    assert.match(body.detail, /league 77 is a head-to-head league/);
    const keys = cacheKeys({ kind: "standings", league: 77, page: 1 });
    assert.equal(cache.stored.get(keys.fresh).maxAge, NOT_FOUND_TTL_SECONDS);
    assert.equal(cache.stored.has(keys.lastGood), false);
    await get("/api/v1/fpl/standings/77?page=1");
    assert.equal(upstream.calls.length, 2, "the refusal is remembered");
  });

  it("says a league FPL does not have is not found, and a page past the end is that page", async () => {
    const { get, upstream } = harness({
      [fpl(upstreamPaths.classicStandings(78, 1))]: status(404),
      [fpl(upstreamPaths.headToHeadStandings(78))]: status(404),
      [fpl(upstreamPaths.classicStandings(314, 9))]: status(404),
    });
    assert.equal((await get("/api/v1/fpl/standings/78?page=1")).body.error, "league_not_found");
    const past = await get("/api/v1/fpl/standings/314?page=9");
    assert.equal(past.body.error, "page_not_found");
    assert.equal(upstream.calls.length, 3, "a later page asks no head-to-head question");
  });
});

describe("the entry bundle", () => {
  it("answers fpl_entry_bundle_v1 exactly as the committed examples show", async () => {
    const examples = await contractFile("fpl_entry_bundle_v1.examples.json");
    const schema = await contractFile("fpl_entry_bundle_v1.schema.json");
    for (const [name, entry] of [
      ["free_hit_walk_back", OPENER],
      ["late_joiner", LATE],
    ]) {
      const { get } = harness(bundleWorld());
      const { response, body, text } = await get(`/api/v1/fpl/entry/${entry}/bundle?gw=10`);
      assert.equal(response.status, 200, name);
      assert.equal(body.contract_version, BUNDLE_CONTRACT);
      assert.deepEqual(problems(schema, body), [], name);
      assert.deepEqual(body, examples[name], name);
      assert.ok(!text.includes(MARKER), name);
    }
  });

  it("reads the held week, walks back past a Free Hit, and reads the opening fifteen", async () => {
    const { get, upstream } = harness(bundleWorld());
    const { body } = await get(`/api/v1/fpl/entry/${OPENER}/bundle?gw=10`);
    assert.deepEqual(
      body.picks.map((picks) => picks.entry_history.event),
      [1, 8, 9],
    );
    assert.equal(body.current_week.gameweek, 9);
    assert.equal(body.current_week.active_chip, "freehit");
    const picksRead = fplCalls(upstream.calls)
      .map((call) => call.url)
      .filter((url) => url.includes("/picks/"));
    assert.deepEqual(picksRead.sort(), [
      fpl(upstreamPaths.picks(OPENER, 1)),
      fpl(upstreamPaths.picks(OPENER, 8)),
      fpl(upstreamPaths.picks(OPENER, 9)),
    ]);
    for (const call of upstream.calls) {
      assert.ok(!call.url.includes("bootstrap-static"), call.url);
    }
  });

  it("reads no picks before the week an entry joined, and no opening picks for it", async () => {
    const { get, upstream } = harness(bundleWorld());
    const { body } = await get(`/api/v1/fpl/entry/${LATE}/bundle?gw=10`);
    assert.deepEqual(
      body.picks.map((picks) => picks.entry_history.event),
      [9],
    );
    assert.deepEqual(body.current_week.pick_order.slice(0, 4), [201, 202, 203, 204]);
    assert.equal(body.current_week.transfer_cost, 4);
    assert.equal(fplCalls(upstream.calls).filter((call) => call.url.includes("/picks/")).length, 1);
  });

  it("carries the current week's block when an earlier table week is asked", async () => {
    const world = bundleWorld();
    const { get } = harness(world);
    const { body } = await get(`/api/v1/fpl/entry/${OPENER}/bundle?gw=9`);
    assert.deepEqual(
      body.picks.map((picks) => picks.entry_history.event),
      [1, 8],
    );
    assert.equal(body.gameweek, 9);
    assert.equal(body.current_week.gameweek, 9);
  });

  it("refuses a table week after the current one without asking FPL", async () => {
    const { get, upstream } = harness(bundleWorld());
    for (const gw of [11, 1]) {
      const { response, body } = await get(`/api/v1/fpl/entry/${OPENER}/bundle?gw=${gw}`);
      assert.equal(response.status, 404, `gw ${gw}`);
      assert.equal(body.error, "not_found");
    }
    assert.equal(fplCalls(upstream.calls).length, 0);
  });

  it("keeps a bundle until the next deadline once the current week is finished", async () => {
    const { get, cache } = harness(bundleWorld());
    await get(`/api/v1/fpl/entry/${OPENER}/bundle?gw=10`);
    const keys = cacheKeys({ kind: "bundle", entry: OPENER, gameweek: 10 });
    const untilDeadline = (deadlineMs(10) - NOW_MS) / 1000;
    assert.equal(cache.stored.get(keys.fresh).maxAge, untilDeadline);
    assert.equal(cache.stored.get(keys.lastGood).maxAge, untilDeadline + LAST_GOOD_EXTRA_SECONDS);
  });

  it("keeps a bundle 10 minutes while the current week is played, or its fixtures unread", async () => {
    const keys = cacheKeys({ kind: "bundle", entry: OPENER, gameweek: 10 });
    const playing = harness(
      bundleWorld({
        week9Fixtures: [
          [91, 1, 2, true],
          [92, 3, 4, false],
        ],
      }),
    );
    await playing.get(`/api/v1/fpl/entry/${OPENER}/bundle?gw=10`);
    assert.equal(playing.cache.stored.get(keys.fresh).maxAge, 600);

    const world = bundleWorld();
    world[fpl(upstreamPaths.fixtures(9))] = status(503);
    const unread = harness(world);
    const { response } = await unread.get(`/api/v1/fpl/entry/${OPENER}/bundle?gw=10`);
    assert.equal(response.status, 200);
    assert.equal(unread.cache.stored.get(keys.fresh).maxAge, 600);
  });

  it("says an entry FPL does not have is not found and remembers it for 10 minutes", async () => {
    const { get, cache } = harness({
      [SCHEDULE_URL]: fixturesJson(),
      [fpl(upstreamPaths.entry(999))]: status(404),
    });
    const { response, body } = await get("/api/v1/fpl/entry/999/bundle?gw=10");
    assert.equal(response.status, 404);
    assert.equal(body.error, "entry_not_found");
    const keys = cacheKeys({ kind: "bundle", entry: 999, gameweek: 10 });
    assert.equal(cache.stored.get(keys.fresh).maxAge, NOT_FOUND_TTL_SECONDS);
  });

  it("reads the current week from the site's fixture list, once per five minutes", async () => {
    const { get, upstream, cache } = harness(bundleWorld());
    await get(`/api/v1/fpl/entry/${OPENER}/bundle?gw=10`);
    await get(`/api/v1/fpl/entry/${LATE}/bundle?gw=10`);
    assert.equal(upstream.calls.filter((call) => call.url === SCHEDULE_URL).length, 1);
    assert.equal(cache.stored.get(SCHEDULE_CACHE_KEY).maxAge, SCHEDULE_TTL_SECONDS);
    assert.deepEqual(Object.keys(JSON.parse(cache.stored.get(SCHEDULE_CACHE_KEY).text).payload), [
      "season",
      "gameweeks",
    ]);
  });
});

describe("the live week", () => {
  it("answers week_live_v1 in the trimmed source A form of the committed examples", async () => {
    const schema = await contractFile("week_live_v1.schema.json");
    const examples = await contractFile("week_live_v1.examples.json");
    const { get } = harness(liveWorld());
    const { response, body, text } = await get("/api/v1/fpl/live/9");
    assert.equal(response.status, 200);
    assert.equal(body.contract_version, LIVE_CONTRACT);
    assert.deepEqual(problems(schema, body), []);
    assert.ok(!text.includes(MARKER));

    // The examples' shape, as source A serves it: no member blocks, no position or club.
    const example = examples.finished;
    const keysOf = (value) => Object.keys(value).sort();
    assert.deepEqual(
      keysOf(body),
      keysOf(example).filter((key) => key !== "members"),
    );
    assert.deepEqual(keysOf(body.fixtures[0]), keysOf(example.fixtures[0]));
    assert.deepEqual(
      keysOf(body.elements[0]),
      keysOf(example.elements[0]).filter((key) => key !== "position" && key !== "club"),
    );
    assert.equal(body.season, "2026-27");
    assert.deepEqual(
      body.elements.map((element) => element.element_id),
      [1, 2, 3, 4, 5],
    );
    assert.deepEqual(
      body.elements.map((element) => element.card_shown),
      [true, false, false, true, true],
    );
  });

  it("keeps an unfinished week 60 s and a finished one until the next deadline", async () => {
    const keys = cacheKeys({ kind: "live", gameweek: 9 });
    const playing = harness(
      liveWorld({
        fixtures: [
          [91, 1, 2, true],
          [92, 3, 4, false],
        ],
      }),
    );
    await playing.get("/api/v1/fpl/live/9");
    assert.equal(playing.cache.stored.get(keys.fresh).maxAge, 60);
    playing.clock.advance(59_000);
    assert.equal(
      (await playing.get("/api/v1/fpl/live/9")).response.headers.get(CACHE_HEADER),
      "hit",
    );
    playing.clock.advance(1_000);
    assert.equal(
      (await playing.get("/api/v1/fpl/live/9")).response.headers.get(CACHE_HEADER),
      "miss",
    );

    const done = harness(liveWorld());
    await done.get("/api/v1/fpl/live/9");
    assert.equal(done.cache.stored.get(keys.fresh).maxAge, (deadlineMs(10) - NOW_MS) / 1000);
  });

  it("answers the current week or an earlier one, never a later one", async () => {
    const { get, upstream } = harness(liveWorld());
    for (const gw of [10, 38]) {
      const { response, body } = await get(`/api/v1/fpl/live/${gw}`);
      assert.equal(response.status, 404, `gw ${gw}`);
      assert.equal(body.error, "not_found");
    }
    assert.equal(fplCalls(upstream.calls).length, 0);
  });
});

describe("the last good copy", () => {
  const cases = [
    [
      "/api/v1/fpl/standings/314?page=1",
      { kind: "standings", league: 314, page: 1 },
      fpl(upstreamPaths.classicStandings(314, 1)),
    ],
    [
      `/api/v1/fpl/entry/${OPENER}/bundle?gw=10`,
      { kind: "bundle", entry: OPENER, gameweek: 10 },
      fpl(upstreamPaths.entry(OPENER)),
    ],
    ["/api/v1/fpl/live/9", { kind: "live", gameweek: 9 }, fpl(upstreamPaths.live(9))],
  ];

  /** One good answer, then the clock moved one second past its fresh copy, then `failure`. */
  async function failsAfterOneGoodAnswer(path, route, url, failure) {
    const world = { ...standingsWorld(), ...bundleWorld(), ...liveWorld() };
    const h = harness(world);
    const good = await h.get(path);
    assert.equal(good.response.status, 200);
    const fresh = h.cache.stored.get(cacheKeys(route).fresh);
    h.clock.advance(fresh.maxAge * 1000 + 1000);
    world[url] = failure;
    return { h, good };
  }

  for (const [label, failure] of [
    ["503", status(503, "The game is being updated.")],
    ["429", status(429)],
    ["a network error", () => new TypeError("fetch failed")],
    ["HTML", () => new Response("<!doctype html><title>x</title>", { status: 200 })],
    ["JSON about something else", () => Response.json({ id: 1, league: { id: 1 } })],
  ]) {
    it(`is served with its original source time when FPL answers ${label}`, async () => {
      for (const [path, route, url] of cases) {
        const { h, good } = await failsAfterOneGoodAnswer(path, route, url, failure);
        const stale = await h.get(path);
        assert.equal(stale.response.status, 200, path);
        assert.equal(stale.response.headers.get(CACHE_HEADER), "last-good", path);
        assertJsonAndMarked(stale.response, path);
        assert.equal(stale.text, good.text, path);
        assert.equal(stale.body.source_time, new Date(NOW_MS).toISOString(), path);
        assert.ok(
          h.lines.some((line) => line.event === "upstream_unavailable"),
          path,
        );
        // A log line says what failed, never which league or entry a visitor asked for.
        for (const id of ["314", String(OPENER)]) {
          assert.ok(!JSON.stringify(h.lines).includes(id), `${path} logs ${id}`);
        }
      }
    });
  }

  it("is not there on a first failure, which answers a JSON 503", async () => {
    for (const failure of [status(503), status(429)]) {
      const { get } = harness({ [fpl(upstreamPaths.classicStandings(314, 1))]: failure });
      const { response, body } = await get("/api/v1/fpl/standings/314?page=1");
      assert.equal(response.status, 503);
      assertJsonAndMarked(response, "503");
      assert.equal(body.error, "upstream_unavailable");
      assert.match(body.detail, /HTTP (503|429)/);
    }
  });

  it("covers the site's fixture list failing too", async () => {
    const world = liveWorld();
    const h = harness(world);
    const good = await h.get("/api/v1/fpl/live/9");
    for (const key of h.cache.stored.keys()) {
      if (!key.includes("/last-good/")) h.cache.stored.delete(key);
    }
    world[SCHEDULE_URL] = status(500);
    const stale = await h.get("/api/v1/fpl/live/9");
    assert.equal(stale.response.headers.get(CACHE_HEADER), "last-good");
    assert.equal(stale.text, good.text);
  });

  it("outlives its fresh copy by two days, and then is gone", async () => {
    assert.equal(LAST_GOOD_EXTRA_SECONDS, 172_800);
    const [path, route, url] = cases[0];
    const { h } = await failsAfterOneGoodAnswer(path, route, url, status(503));
    h.clock.advance(LAST_GOOD_EXTRA_SECONDS * 1000);
    const { response } = await h.get(path);
    assert.equal(response.status, 503);
  });
});

describe("the deployment", () => {
  it("is one route under /api/v1/fpl/ on the site's host, with no workers.dev or preview address", async () => {
    const config = await readFile(new URL("../wrangler.toml", import.meta.url), "utf8");
    const patterns = [...config.matchAll(/pattern\s*=\s*"([^"]*)"/g)].map((match) => match[1]);
    assert.deepEqual(patterns, ["squadopt.mymandev.com/api/v1/fpl/*"]);
    assert.match(config, /zone_name\s*=\s*"mymandev\.com"/);
    assert.match(config, /^name = "squadopt-fpl-proxy"$/m);
    assert.match(config, /^main = "src\/index\.js"$/m);
    assert.match(config, /^workers_dev = false$/m);
    assert.match(config, /^preview_urls = false$/m);
    // No KV namespace, no cron and no variables: the Cache API holds every copy.
    assert.doesNotMatch(config, /kv_namespaces|\[triggers\]|crons|\[vars\]/);
    assert.match(config, /^\[observability\.logs\]\ninvocation_logs = false$/m);

    const probe = await readFile(new URL("../../fpl-probe/wrangler.toml", import.meta.url), "utf8");
    const date = (text) => /^compatibility_date = "([0-9-]+)"$/m.exec(text)?.[1];
    assert.equal(date(config), date(probe));
    // The probe's prefix route and this one never take each other's paths.
    assert.ok(!"/api/v1/fpl-probe".startsWith("/api/v1/fpl/"));
    assert.ok(!"/api/v1/fpl/standings/1".startsWith("/api/v1/fpl-probe"));
  });

  it("sends the capture's own user agent", async () => {
    const capture = await readFile(
      new URL("src/squadopt/platform/fpl_capture.py", REPOSITORY),
      "utf8",
    );
    const declared = /^USER_AGENT = "([^"]+)"$/m.exec(capture);
    assert.ok(declared, "fpl_capture.py no longer declares USER_AGENT on one line");
    assert.equal(USER_AGENT, declared[1]);
    const base = /^BASE_URL = "([^"]+)"$/m.exec(capture);
    assert.equal(fpl(""), `${base[1]}/`);
  });

  it("exports nothing from the entry point but the handlers", async () => {
    const module = await import("../src/index.js");
    assert.deepEqual(Object.keys(module), ["default"]);
    assert.equal(typeof entryPoint.fetch, "function");
    assert.equal(entryPoint.scheduled, undefined);
  });
});

describe("the schema reader these tests use", () => {
  it("accepts the committed examples and refuses what jsonschema refuses", async () => {
    const schema = await contractFile("week_live_v1.schema.json");
    const examples = await contractFile("week_live_v1.examples.json");
    for (const example of Object.values(examples)) assert.deepEqual(problems(schema, example), []);
    const damaged = [
      { ...examples.finished, raw_response: "private" },
      { ...examples.finished, contract_version: "live_score_v1" },
      { ...examples.finished, source_time: "2026-10-10T20:00:00+03:00" },
      { ...examples.finished, gameweek: 39 },
      { ...examples.finished, members: [{ ...examples.finished.members[0], active_chip: "x" }] },
      { ...examples.finished, elements: [{ ...examples.finished.elements[0], points: 1.5 }] },
      { ...examples.finished, fixtures: [{ ...examples.finished.fixtures[0], finished: "true" }] },
    ];
    for (const document of damaged) assert.notDeepEqual(problems(schema, document), []);
    const bundle = await contractFile("fpl_entry_bundle_v1.schema.json");
    const bundles = await contractFile("fpl_entry_bundle_v1.examples.json");
    const late = bundles.late_joiner;
    assert.deepEqual(problems(bundle, late), []);
    assert.deepEqual(problems(bundle, { ...late, current_week: null }), []);
    assert.notDeepEqual(problems(bundle, { ...late, current_week: { entry_id: 1 } }), []);
    assert.throws(() => problems({ oneOf: [] }, 1), /does not know the keyword oneOf/);
  });
});
