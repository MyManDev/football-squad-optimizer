// The FPL forwarder's fetch handler: three GET routes under /api/v1/fpl/ on the site's host.
//
// Each route reads FPL on the visitor's request and answers with one trimmed, versioned
// document (proxy.js says which fields leave the Worker), never with FPL's own JSON. A copy of
// each answer is kept in this data centre's cache for as long as proxy.js allows, and a second
// copy, the last good one, is kept apart for two days longer. When FPL refuses (429), fails
// (5xx), sends something unreadable or cannot be reached, that copy is served with its original
// source time, and without one the answer is a JSON 503. Every answer is JSON and carries
// x-squadopt-fpl: 1.
// The current week and the next deadline come from the site's own /data/fixtures.json; FPL's
// bootstrap-static is never read. See docs/architecture/decisions/0012-fpl-forwarder.md.
//
// index.js is the entry point and exports one set of these handlers; tests build their own.

import {
  CACHE_HEADER,
  FPL_API,
  LAST_GAMEWEEK,
  MARKER_HEADER,
  MARKER_VALUE,
  NOT_FOUND_TTL_SECONDS,
  SCHEDULE_CACHE_KEY,
  SCHEDULE_TTL_SECONDS,
  SCHEDULE_URL,
  STANDINGS_TTL_SECONDS,
  UPSTREAM_TIMEOUT_MS,
  USER_AGENT,
  UnreadableError,
  bundleDocument,
  bundleTtl,
  bundleWeekAllowed,
  cacheKeys,
  declaresLeague,
  entryPart,
  fixturesPart,
  freeHitWeek,
  historyPart,
  lastGoodTtl,
  liveDocument,
  liveTtl,
  liveWeekAllowed,
  memberWeekFrom,
  opensAtGameweekOne,
  picksPart,
  routeFor,
  scheduleFrom,
  standingsDocument,
  transfersPart,
  upstreamPaths,
  weekFinished,
  weekState,
} from "./proxy.js";

const JSON_TYPE = "application/json; charset=utf-8";

const JSON_HEADERS = {
  "content-type": JSON_TYPE,
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  [MARKER_HEADER]: MARKER_VALUE,
};

function answerText(status, text, headers = {}) {
  return new Response(text, { status, headers: { ...JSON_HEADERS, ...headers } });
}

function answer(status, body, headers = {}) {
  return answerText(status, JSON.stringify(body), headers);
}

/** FPL or the site gave no readable answer: serve the last good copy, or 503. */
class Unavailable extends Error {
  constructor(message, status = null) {
    super(message);
    this.name = "Unavailable";
    this.status = status;
  }
}

/** FPL answered 404. What that means depends on which document was asked for. */
class UpstreamNotFound extends Error {
  constructor(path) {
    super(`FPL answered 404 for ${path}`);
    this.name = "UpstreamNotFound";
  }
}

/** A definite answer that is not a document, kept for `seconds` (0: not kept). */
class Refusal extends Error {
  constructor(status, body, seconds) {
    super(body.error);
    this.name = "Refusal";
    this.status = status;
    this.body = body;
    this.seconds = seconds;
  }
}

/**
 * What a log line says about a failure: its kind and, for an HTTP answer, its status. Never
 * its message, which can hold the entry or league a visitor asked for.
 */
function failure(error) {
  const name = error instanceof Error ? error.name : typeof error;
  return Number.isInteger(error?.status)
    ? { failure: name, status: error.status }
    : { failure: name };
}

function describe(error) {
  if (error && (error.name === "TimeoutError" || error.name === "AbortError")) {
    return `no answer within ${UPSTREAM_TIMEOUT_MS} ms`;
  }
  return error instanceof Error ? `${error.name}: ${error.message}` : String(error);
}

const iso = (ms) => new Date(ms).toISOString();

/**
 * The handlers. `options` replaces what a test cannot use: `fetch` (FPL and the site), `cache`
 * (caches.default), `now` (the clock) and `log` (console lines). index.js passes none.
 */
export function createWorker(options = {}) {
  const now = options.now ?? (() => Date.now());
  const fetchImpl = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
  const log = options.log ?? ((event, fields) => console.log(JSON.stringify({ event, ...fields })));
  const cacheOf = () => options.cache ?? globalThis.caches?.default ?? null;

  async function cacheGet(key) {
    const cache = cacheOf();
    if (cache === null) return null;
    try {
      return (await cache.match(new Request(key))) ?? null;
    } catch (error) {
      log("cache_read_failed", failure(error));
      return null;
    }
  }

  async function cachePut(key, status, text, seconds) {
    const cache = cacheOf();
    if (cache === null || !(seconds >= 1)) return;
    try {
      await cache.put(
        new Request(key),
        new Response(text, {
          status,
          headers: { "content-type": JSON_TYPE, "cache-control": `max-age=${seconds}` },
        }),
      );
    } catch (error) {
      log("cache_write_failed", failure(error));
    }
  }

  /** One FPL document, parsed. `cacheTtl: 0` keeps Cloudflare's own cache out of the way. */
  async function upstream(path) {
    let response;
    try {
      response = await fetchImpl(`${FPL_API}${path}`, {
        method: "GET",
        headers: { "user-agent": USER_AGENT, accept: "application/json" },
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
        cf: { cacheTtl: 0 },
      });
    } catch (error) {
      throw new Unavailable(`FPL could not be reached: ${describe(error)}`);
    }
    if (response.status === 404) throw new UpstreamNotFound(path);
    if (!response.ok) {
      throw new Unavailable(`FPL answered HTTP ${response.status}`, response.status);
    }
    try {
      return await response.json();
    } catch {
      throw new Unavailable("FPL answered with something that is not JSON");
    }
  }

  /** A part of a document whose 404 means FPL failed, not that the thing does not exist. */
  async function part(path) {
    try {
      return await upstream(path);
    } catch (error) {
      if (error instanceof UpstreamNotFound) throw new Unavailable(error.message, 404);
      throw error;
    }
  }

  /** The season and its deadlines, from the site's fixture list, kept for 5 minutes. */
  async function schedule() {
    const hit = await cacheGet(SCHEDULE_CACHE_KEY);
    if (hit !== null) {
      try {
        return scheduleFrom(JSON.parse(await hit.text()));
      } catch (error) {
        log("schedule_copy_unreadable", failure(error));
      }
    }
    let document;
    try {
      const response = await fetchImpl(SCHEDULE_URL, {
        method: "GET",
        headers: { accept: "application/json" },
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      document = await response.json();
    } catch (error) {
      throw new Unavailable(`the site's fixture list could not be read: ${describe(error)}`);
    }
    const read = scheduleFrom(document);
    // Kept in fixtures_v1's own shape, trimmed to what the schedule reads, so a copy is read
    // back by the same reader as the site's file.
    const copy = {
      contract_version: "fixtures_v1",
      payload: { season: read.season, gameweeks: read.deadlines },
    };
    await cachePut(SCHEDULE_CACHE_KEY, 200, JSON.stringify(copy), SCHEDULE_TTL_SECONDS);
    return read;
  }

  async function standings({ league, page }) {
    let raw;
    try {
      raw = await upstream(upstreamPaths.classicStandings(league, page));
    } catch (error) {
      if (!(error instanceof UpstreamNotFound)) throw error;
      throw await notClassic(league, page);
    }
    const document = standingsDocument(raw, { league, page, sourceTime: iso(now()) });
    return { document, seconds: STANDINGS_TTL_SECONDS };
  }

  /**
   * FPL has no classic page 1 for this league. As the capture does (classic_standings in
   * src/squadopt/platform/fpl_capture.py), the head-to-head table is asked once, to say which
   * refusal it is. A later page FPL does not have is refused as that page.
   */
  async function notClassic(league, page) {
    if (page > 1) {
      return new Refusal(
        404,
        {
          error: "page_not_found",
          league,
          page,
          detail: `FPL has no page ${page} of league ${league}`,
        },
        NOT_FOUND_TTL_SECONDS,
      );
    }
    let raw = null;
    try {
      raw = await upstream(upstreamPaths.headToHeadStandings(league));
    } catch (error) {
      if (!(error instanceof UpstreamNotFound)) throw error;
    }
    if (raw !== null && declaresLeague(raw, league)) {
      return new Refusal(
        404,
        {
          error: "head_to_head_league",
          league,
          detail:
            `league ${league} is a head-to-head league; ` +
            "the forwarder serves classic leagues only",
        },
        NOT_FOUND_TTL_SECONDS,
      );
    }
    return new Refusal(
      404,
      { error: "league_not_found", league, detail: `FPL has no classic league ${league}` },
      NOT_FOUND_TTL_SECONDS,
    );
  }

  /** Whether every fixture of a week is finished; a failed or unreadable answer says no. */
  async function finished(gameweek) {
    try {
      return weekFinished(fixturesPart(await part(upstreamPaths.fixtures(gameweek)), gameweek));
    } catch (error) {
      log("fixtures_unread", { gameweek, ...failure(error) });
      return false;
    }
  }

  async function bundle({ entry, gameweek }) {
    const plan = await schedule();
    const { latestStarted, nextDeadlineMs } = weekState(plan, now());
    if (!bundleWeekAllowed(gameweek, latestStarted)) {
      const last = Math.min(LAST_GAMEWEEK, latestStarted + 1);
      const detail =
        last < 2
          ? "no gameweek has started, so no entry has picks yet"
          : `gw is the table gameweek, from 2 to ${last} now`;
      throw new Refusal(404, { error: "not_found", detail }, 0);
    }

    let entryRaw;
    try {
      entryRaw = await upstream(upstreamPaths.entry(entry));
    } catch (error) {
      if (!(error instanceof UpstreamNotFound)) throw error;
      throw new Refusal(
        404,
        { error: "entry_not_found", entry, detail: `FPL has no entry ${entry}` },
        NOT_FOUND_TTL_SECONDS,
      );
    }
    const entryRow = entryPart(entryRaw, entry);
    const [historyRaw, transfersRaw] = await Promise.all([
      part(upstreamPaths.history(entry)),
      part(upstreamPaths.transfers(entry)),
    ]);
    const parts = {
      entry: entryRow,
      history: historyPart(historyRaw),
      transfers: transfersPart(transfersRaw),
    };

    // Each picks answer is read once, however many uses it has.
    const answers = new Map();
    const picksAnswer = async (week) => {
      if (!answers.has(week)) answers.set(week, await part(upstreamPaths.picks(entry, week)));
      return answers.get(week);
    };

    // The held squad is the table gameweek's previous week. A Free Hit squad lasts one week, so
    // the walk goes back past each Free Hit week to the squad the member holds, never before
    // the week the entry joined (heldSquadBasis in web/src/features/league/entryState/rules.ts).
    const picks = new Map();
    const first = entryRow.started_event;
    for (let week = gameweek - 1; week >= first; week -= 1) {
      const read = picksPart(await picksAnswer(week), week);
      picks.set(week, read);
      if (!freeHitWeek(read)) break;
    }
    // The opening fifteen, which the purchase-price replay starts from, for an entry whose
    // history starts at gameweek 1 (purchase_price_endpoints in fpl_capture.py).
    if (opensAtGameweekOne(parts.history) && !picks.has(1)) {
      picks.set(1, picksPart(await picksAnswer(1), 1));
    }
    const currentWeek =
      latestStarted >= first
        ? memberWeekFrom(await picksAnswer(latestStarted), entry, latestStarted)
        : null;
    const settled = await finished(latestStarted);

    const document = bundleDocument({
      entry,
      gameweek,
      sourceTime: iso(now()),
      parts,
      picks,
      currentWeek,
    });
    return { document, seconds: bundleTtl({ settled, nowMs: now(), nextDeadlineMs }) };
  }

  async function live({ gameweek }) {
    const plan = await schedule();
    const { latestStarted, nextDeadlineMs } = weekState(plan, now());
    if (!liveWeekAllowed(gameweek, latestStarted)) {
      const detail =
        latestStarted === 0
          ? "no gameweek has started yet"
          : `a live week is the current one or an earlier one, from 1 to ${latestStarted} now`;
      throw new Refusal(404, { error: "not_found", detail }, 0);
    }
    const [liveRaw, fixturesRaw] = await Promise.all([
      part(upstreamPaths.live(gameweek)),
      part(upstreamPaths.fixtures(gameweek)),
    ]);
    const document = liveDocument({
      live: liveRaw,
      fixtures: fixturesRaw,
      season: plan.season,
      gameweek,
      sourceTime: iso(now()),
    });
    const seconds = liveTtl({
      finished: weekFinished(document.fixtures),
      nowMs: now(),
      nextDeadlineMs,
    });
    return { document, seconds };
  }

  const builders = { standings, bundle, live };

  async function serve(route) {
    const keys = cacheKeys(route);
    const hit = await cacheGet(keys.fresh);
    if (hit !== null) return answerText(hit.status, await hit.text(), { [CACHE_HEADER]: "hit" });

    let built;
    try {
      built = await builders[route.kind](route);
    } catch (error) {
      if (error instanceof Refusal) {
        await cachePut(keys.fresh, error.status, JSON.stringify(error.body), error.seconds);
        return answer(error.status, error.body);
      }
      if (!(error instanceof Unavailable || error instanceof UnreadableError)) throw error;
      log("upstream_unavailable", { route: route.kind, ...failure(error) });
      const good = await cacheGet(keys.lastGood);
      if (good !== null) {
        return answerText(200, await good.text(), { [CACHE_HEADER]: "last-good" });
      }
      return answer(
        503,
        { error: "upstream_unavailable", detail: error.message },
        { "retry-after": "60" },
      );
    }

    const text = JSON.stringify(built.document);
    await cachePut(keys.fresh, 200, text, built.seconds);
    await cachePut(keys.lastGood, 200, text, lastGoodTtl(built.seconds));
    return answerText(200, text, { [CACHE_HEADER]: "miss" });
  }

  return {
    async fetch(request) {
      try {
        const route = routeFor(request.method, new URL(request.url));
        if (route.status !== undefined) {
          const headers = route.status === 405 ? { allow: "GET" } : {};
          return answer(route.status, route.body, headers);
        }
        return await serve(route);
      } catch (error) {
        log("request_failed", failure(error));
        return answer(500, { error: "internal" });
      }
    },
  };
}
