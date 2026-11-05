// The FPL forwarder's rules, run with node --test (no Cloudflare account, no network).
//
// proxy.js is pure: which request is allowed, which fields of FPL's answers leave the Worker,
// and how long each copy lives. Each is tested here directly; worker.test.mjs drives the same
// rules through the fetch handler.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  BUNDLE_PLAYING_TTL_SECONDS,
  CACHE_PREFIX,
  LAST_GOOD_EXTRA_SECONDS,
  LIVE_PLAYING_TTL_SECONDS,
  MAX_STANDINGS_PAGE,
  MAX_TTL_SECONDS,
  SEASON_END_TTL_SECONDS,
  UnreadableError,
  bundleTtl,
  bundleWeekAllowed,
  cacheKeys,
  entryPart,
  fixturesPart,
  historyPart,
  lastGoodTtl,
  liveDocument,
  liveTtl,
  liveWeekAllowed,
  memberWeekFrom,
  picksPart,
  routeFor,
  scheduleFrom,
  standingsDocument,
  transfersPart,
  untilNextDeadline,
  upstreamPaths,
  weekFinished,
  weekState,
} from "../src/proxy.js";
import {
  MARKER,
  SITE,
  deadlineMs,
  entryAnswer,
  fifteen,
  fixturesAnswer,
  fixturesJson,
  historyAnswer,
  liveAnswer,
  picksAnswer,
  standingsPage,
  transfersAnswer,
} from "./support.mjs";

const route = (path, method = "GET") => routeFor(method, new URL(`${SITE}${path}`));
const SOURCE_TIME = "2026-10-19T17:30:00.000Z";

describe("which requests are answered", () => {
  it("reads the three routes with their ids and query", () => {
    assert.deepEqual(route("/api/v1/fpl/standings/352490?page=1"), {
      kind: "standings",
      league: 352490,
      page: 1,
    });
    assert.deepEqual(route(`/api/v1/fpl/standings/7?page=${MAX_STANDINGS_PAGE}`), {
      kind: "standings",
      league: 7,
      page: 20,
    });
    assert.deepEqual(route("/api/v1/fpl/entry/123456/bundle?gw=10"), {
      kind: "bundle",
      entry: 123456,
      gameweek: 10,
    });
    assert.deepEqual(route("/api/v1/fpl/live/38"), { kind: "live", gameweek: 38 });
  });

  it("refuses an id that is not a positive integer with a 404", () => {
    for (const path of [
      "/api/v1/fpl/standings/abc?page=1",
      "/api/v1/fpl/standings/0?page=1",
      "/api/v1/fpl/standings/-5?page=1",
      "/api/v1/fpl/standings/012?page=1",
      "/api/v1/fpl/standings/1.5?page=1",
      "/api/v1/fpl/standings/1e3?page=1",
      "/api/v1/fpl/standings/%31?page=1",
      "/api/v1/fpl/standings/1234567890123456?page=1",
      "/api/v1/fpl/entry/x/bundle?gw=10",
      "/api/v1/fpl/entry/0/bundle?gw=10",
      "/api/v1/fpl/entry/-1/bundle?gw=10",
      "/api/v1/fpl/live/0",
      "/api/v1/fpl/live/-1",
      "/api/v1/fpl/live/nine",
      "/api/v1/fpl/live/09",
    ]) {
      const answer = route(path);
      assert.equal(answer.status, 404, path);
      assert.equal(answer.body.error, "not_found", path);
    }
  });

  it("refuses a page above 20, a gameweek above 38 and a query that is not exactly the route's", () => {
    for (const path of [
      "/api/v1/fpl/standings/314?page=21",
      "/api/v1/fpl/standings/314?page=0",
      "/api/v1/fpl/standings/314",
      "/api/v1/fpl/standings/314?page=1&page=2",
      "/api/v1/fpl/standings/314?page=1&phase=1",
      "/api/v1/fpl/standings/314?page_standings=1",
      "/api/v1/fpl/entry/101/bundle?gw=39",
      "/api/v1/fpl/entry/101/bundle",
      "/api/v1/fpl/entry/101/bundle?gw=10&x=1",
      "/api/v1/fpl/live/39",
      "/api/v1/fpl/live/9?gw=9",
    ]) {
      assert.equal(route(path).status, 404, path);
    }
  });

  it("refuses every path outside the allowlist, FPL's own paths among them", () => {
    for (const path of [
      "/api/v1/fpl/",
      "/api/v1/fpl/bootstrap-static/",
      "/api/v1/fpl/entry/101/",
      "/api/v1/fpl/entry/101/history/",
      "/api/v1/fpl/entry/101/event/9/picks/",
      "/api/v1/fpl/leagues-classic/314/standings/",
      "/api/v1/fpl/standings/314/?page=1",
      "/api/v1/fpl/entry/101/bundle/?gw=10",
      "/api/v1/fpl/live/9/",
      "/api/v1/fpl/.cache/v1/fresh/live/9",
      "/api/v1/fpl-probe",
      "/",
    ]) {
      const answer = route(path);
      assert.equal(answer.status, 404, path);
      assert.equal(answer.body.error, "not_found", path);
    }
  });

  it("answers any method but GET on a route's path with a 405", () => {
    for (const method of ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]) {
      for (const path of [
        "/api/v1/fpl/standings/314?page=1",
        "/api/v1/fpl/entry/101/bundle?gw=10",
        "/api/v1/fpl/live/9",
      ]) {
        const answer = route(path, method);
        assert.equal(answer.status, 405, `${method} ${path}`);
        assert.equal(answer.body.error, "method_not_allowed");
      }
    }
    assert.equal(route("/api/v1/fpl/other", "POST").status, 404);
  });
});

describe("cache keys", () => {
  it("keep a fresh copy and a last good copy apart, under the Worker's own 404 path", () => {
    const keys = cacheKeys({ kind: "standings", league: 314, page: 2 });
    assert.equal(keys.fresh, `${SITE}${CACHE_PREFIX}fresh/standings/314/2`);
    assert.equal(keys.lastGood, `${SITE}${CACHE_PREFIX}last-good/standings/314/2`);
    assert.equal(
      cacheKeys({ kind: "bundle", entry: 101, gameweek: 10 }).fresh,
      `${SITE}${CACHE_PREFIX}fresh/bundle/101/10`,
    );
    assert.equal(
      cacheKeys({ kind: "live", gameweek: 9 }).lastGood,
      `${SITE}${CACHE_PREFIX}last-good/live/9`,
    );
    const path = new URL(keys.fresh).pathname;
    assert.equal(routeFor("GET", new URL(keys.fresh)).status, 404, path);
  });

  it("name only the paths FPL is asked, never bootstrap-static", () => {
    const paths = [
      upstreamPaths.classicStandings(314, 3),
      upstreamPaths.headToHeadStandings(314),
      upstreamPaths.entry(101),
      upstreamPaths.history(101),
      upstreamPaths.transfers(101),
      upstreamPaths.picks(101, 9),
      upstreamPaths.live(9),
      upstreamPaths.fixtures(9),
    ];
    assert.deepEqual(paths, [
      "leagues-classic/314/standings/?page_standings=3",
      "leagues-h2h/314/standings/",
      "entry/101/",
      "entry/101/history/",
      "entry/101/transfers/",
      "entry/101/event/9/picks/",
      "event/9/live/",
      "fixtures/?event=9",
    ]);
    assert.ok(paths.every((path) => !path.includes("bootstrap")));
  });
});

describe("the schedule from the site's fixture list", () => {
  const schedule = scheduleFrom(fixturesJson());

  it("keeps the season and every deadline, nothing else", () => {
    assert.equal(schedule.season, "2026-27");
    assert.equal(schedule.deadlines.length, 38);
    assert.deepEqual(Object.keys(schedule.deadlines[0]), ["gameweek", "deadline_utc"]);
  });

  it("finds the latest started week and the next deadline", () => {
    assert.deepEqual(weekState(schedule, deadlineMs(1) - 1), {
      latestStarted: 0,
      nextDeadlineMs: deadlineMs(1),
    });
    assert.deepEqual(weekState(schedule, deadlineMs(9)), {
      latestStarted: 9,
      nextDeadlineMs: deadlineMs(10),
    });
    assert.deepEqual(weekState(schedule, deadlineMs(9) + 1), {
      latestStarted: 9,
      nextDeadlineMs: deadlineMs(10),
    });
    assert.deepEqual(weekState(schedule, deadlineMs(38) + 1), {
      latestStarted: 38,
      nextDeadlineMs: null,
    });
  });

  it("refuses a list that is not fixtures_v1, or whose deadlines do not rise", () => {
    assert.throws(() => scheduleFrom({ payload: {} }), UnreadableError);
    assert.throws(() => scheduleFrom("<!doctype html>"), UnreadableError);
    const muddled = fixturesJson();
    muddled.payload.gameweeks[3].deadline_utc = muddled.payload.gameweeks[2].deadline_utc;
    assert.throws(() => scheduleFrom(muddled), /do not rise/);
    const repeated = fixturesJson();
    repeated.payload.gameweeks[3].gameweek = 3;
    assert.throws(() => scheduleFrom(repeated), UnreadableError);
    const season = fixturesJson();
    season.payload.season = "2026";
    assert.throws(() => scheduleFrom(season), /season/);
  });

  it("allows a bundle for the table gameweek up to the week after the latest started one", () => {
    assert.equal(bundleWeekAllowed(10, 9), true);
    assert.equal(bundleWeekAllowed(2, 9), true);
    assert.equal(bundleWeekAllowed(11, 9), false);
    assert.equal(bundleWeekAllowed(1, 9), false);
    assert.equal(bundleWeekAllowed(2, 0), false);
    assert.equal(bundleWeekAllowed(38, 38), true);
  });

  it("allows a live week up to the latest started one", () => {
    assert.equal(liveWeekAllowed(9, 9), true);
    assert.equal(liveWeekAllowed(1, 9), true);
    assert.equal(liveWeekAllowed(10, 9), false);
    assert.equal(liveWeekAllowed(1, 0), false);
  });
});

describe("how long a copy lives", () => {
  const now = deadlineMs(9) + 3600_000;
  const next = deadlineMs(10);
  const toDeadline = (next - now) / 1000;

  it("keeps a live week 60 s while played and until the next deadline once finished", () => {
    assert.equal(liveTtl({ finished: false, nowMs: now, nextDeadlineMs: next }), 60);
    assert.equal(LIVE_PLAYING_TTL_SECONDS, 60);
    assert.equal(liveTtl({ finished: true, nowMs: now, nextDeadlineMs: next }), toDeadline);
  });

  it("keeps a bundle 10 minutes while its week is played, never past the next deadline", () => {
    assert.equal(bundleTtl({ settled: false, nowMs: now, nextDeadlineMs: next }), 600);
    assert.equal(BUNDLE_PLAYING_TTL_SECONDS, 600);
    assert.equal(bundleTtl({ settled: true, nowMs: now, nextDeadlineMs: next }), toDeadline);
    const late = next - 90_000;
    assert.equal(bundleTtl({ settled: false, nowMs: late, nextDeadlineMs: next }), 90);
    assert.equal(bundleTtl({ settled: true, nowMs: next, nextDeadlineMs: next }), 0);
  });

  it("caps a copy at a day after the last deadline and at a week otherwise", () => {
    assert.equal(untilNextDeadline(now, null), SEASON_END_TTL_SECONDS);
    assert.equal(untilNextDeadline(now, now + 30 * 86_400_000), MAX_TTL_SECONDS);
    assert.equal(untilNextDeadline(now, now - 1000), 0);
  });

  it("keeps the last good copy two days past its fresh copy", () => {
    assert.equal(lastGoodTtl(600), 600 + LAST_GOOD_EXTRA_SECONDS);
    assert.equal(lastGoodTtl(0), LAST_GOOD_EXTRA_SECONDS);
  });

  it("calls a week finished only when it has fixtures and all are finished", () => {
    assert.equal(weekFinished([]), false);
    assert.equal(weekFinished([{ finished: true }, { finished: false }]), false);
    assert.equal(weekFinished([{ finished: true }, { finished: true }]), true);
  });
});

/** Every string anywhere in a value. */
function strings(value) {
  return JSON.stringify(value);
}

describe("trimming", () => {
  it("keeps of a standings page only the league, the page and each row's eight fields", () => {
    const document = standingsDocument(standingsPage({ page: 2, hasNext: true }), {
      league: 314,
      page: 2,
      sourceTime: SOURCE_TIME,
    });
    assert.deepEqual(Object.keys(document), [
      "contract_version",
      "league",
      "page",
      "has_next",
      "last_updated_data",
      "source_time",
      "results",
    ]);
    assert.equal(document.contract_version, "fpl_league_standings_v1");
    assert.deepEqual(document.league, { id: 314, name: "Synthetic League", scoring: "classic" });
    assert.deepEqual(Object.keys(document.results[0]), [
      "entry",
      "entry_name",
      "player_name",
      "rank",
      "rank_sort",
      "last_rank",
      "total",
      "event_total",
    ]);
    assert.equal(document.results[0].rank, 51);
    assert.ok(!strings(document).includes(MARKER));
  });

  it("refuses a standings answer for another league or another page", () => {
    const page = standingsPage({ league: 314, page: 1 });
    assert.throws(
      () => standingsDocument(page, { league: 315, page: 1, sourceTime: SOURCE_TIME }),
      /league 315/,
    );
    assert.throws(
      () => standingsDocument(page, { league: 314, page: 2, sourceTime: SOURCE_TIME }),
      /page 2/,
    );
    const repeated = standingsPage({ rows: 2 });
    repeated.standings.results[1].entry = repeated.standings.results[0].entry;
    assert.throws(
      () => standingsDocument(repeated, { league: 314, page: 1, sourceTime: SOURCE_TIME }),
      /appears twice/,
    );
  });

  it("keeps of an entry only its id, name and joining week", () => {
    assert.deepEqual(entryPart(entryAnswer(101, { started: 3 }), 101), {
      id: 101,
      name: "Synthetic XI",
      started_event: 3,
    });
    assert.throws(() => entryPart(entryAnswer(102), 101), /entry 101/);
  });

  it("keeps of the history each week's transfers, cost and bank, and the chips", () => {
    const history = historyPart(
      historyAnswer({
        weeks: [1, 2],
        chips: [{ name: "wildcard", event: 2 }],
        transfers: { 2: 3 },
      }),
    );
    assert.deepEqual(history, {
      current: [
        { event: 1, event_transfers: 0, event_transfers_cost: 0, bank: 5 },
        { event: 2, event_transfers: 3, event_transfers_cost: 0, bank: 5 },
      ],
      chips: [{ name: "wildcard", event: 2 }],
    });
    const unknownBank = historyAnswer({ weeks: [1] });
    unknownBank.current[0].bank = null;
    assert.equal(historyPart(unknownBank).current[0].bank, null);
  });

  it("keeps of each transfer the seven fields the price replay reads", () => {
    const [row] = transfersPart(transfersAnswer(101, [[2, 120, 114, 1]]));
    assert.deepEqual(Object.keys(row), [
      "entry",
      "event",
      "time",
      "element_in",
      "element_in_cost",
      "element_out",
      "element_out_cost",
    ]);
    assert.throws(() => transfersPart({ results: [] }), UnreadableError);
  });

  it("keeps of a picks answer the fifteen, the substitutions, the chip, bank and value", () => {
    const raw = picksAnswer(202, 9, {
      named: fifteen(200),
      captain: 205,
      vice: 206,
      subs: [[203, 213]],
    });
    const picks = picksPart(raw, 9);
    assert.deepEqual(Object.keys(picks), [
      "active_chip",
      "automatic_subs",
      "entry_history",
      "picks",
    ]);
    assert.deepEqual(picks.entry_history, { event: 9, bank: 5, value: 1003 });
    assert.deepEqual(picks.automatic_subs, [
      { entry: 202, event: 9, element_in: 213, element_out: 203 },
    ]);
    assert.deepEqual(Object.keys(picks.picks[0]), [
      "element",
      "position",
      "multiplier",
      "is_captain",
      "is_vice_captain",
    ]);
    // FPL's positions are kept as FPL wrote them: the picks reader undoes nothing.
    assert.equal(picks.picks[2].element, 213);
    assert.ok(!strings(picks).includes(MARKER));
    assert.ok(!("points" in picks.entry_history));
    assert.throws(() => picksPart(raw, 8), /gameweek 8/);
    const bare = picksAnswer(202, 9, { named: fifteen(200), captain: 205, vice: 206 });
    delete bare.automatic_subs;
    delete bare.active_chip;
    assert.deepEqual(picksPart(bare, 9).automatic_subs, []);
    assert.equal(picksPart(bare, 9).active_chip, null);
  });
});

describe("the in-progress member week", () => {
  const named = fifteen(200);
  const base = { named, captain: 205, vice: 206, cost: 4, points: 47 };

  it("is the named order, captain, vice, chip, transfer cost and points of one picks answer", () => {
    assert.deepEqual(memberWeekFrom(picksAnswer(202, 9, base), 202, 9), {
      entry_id: 202,
      gameweek: 9,
      pick_order: named,
      captain: 205,
      vice: 206,
      active_chip: null,
      transfer_cost: 4,
      entry_history_points: 47,
    });
  });

  it("undoes FPL's automatic substitutions to give the order named at the deadline", () => {
    const swapped = picksAnswer(202, 9, {
      ...base,
      subs: [
        [203, 213],
        [207, 214],
      ],
    });
    assert.equal(swapped.picks[2].element, 213, "FPL moved the substitute into position 3");
    assert.deepEqual(memberWeekFrom(swapped, 202, 9).pick_order, named);
    const kept = picksAnswer(202, 9, { ...base, subs: [[203, 213]], keepNamed: true });
    assert.deepEqual(memberWeekFrom(kept, 202, 9).pick_order, named);
  });

  it("brings back a captain FPL moved to the bench", () => {
    const benched = picksAnswer(202, 9, { ...base, subs: [[205, 212]] });
    assert.ok(benched.picks.find((row) => row.element === 205).position > 11);
    const week = memberWeekFrom(benched, 202, 9);
    assert.equal(week.captain, 205);
    assert.deepEqual(week.pick_order, named);
  });

  it("is left out when week_live_v1 cannot state it", () => {
    const cases = {
      "an unknown chip": picksAnswer(202, 9, { ...base, chip: "manager" }),
      "a substitution of another week": picksAnswer(202, 9, { ...base, subs: [[203, 213]] }),
      "a vice on the bench": picksAnswer(202, 9, { ...base, vice: 213 }),
      "no transfer cost": picksAnswer(202, 9, base),
      "two captains": picksAnswer(202, 9, base),
    };
    cases["a substitution of another week"].automatic_subs[0].event = 8;
    delete cases["no transfer cost"].entry_history.event_transfers_cost;
    cases["two captains"].picks[0].is_captain = true;
    for (const [name, raw] of Object.entries(cases)) {
      assert.equal(memberWeekFrom(raw, 202, 9), null, name);
    }
    const noPoints = picksAnswer(202, 9, base);
    delete noPoints.entry_history.points;
    assert.equal("entry_history_points" in memberWeekFrom(noPoints, 202, 9), false);
  });

  it("accepts each chip week_live_v1 names", () => {
    for (const chip of ["3xc", "bboost", "freehit", "wildcard"]) {
      assert.equal(
        memberWeekFrom(picksAnswer(202, 9, { ...base, chip }), 202, 9).active_chip,
        chip,
      );
    }
  });
});

describe("the live week", () => {
  it("keeps each element's points, minutes and card, and each fixture's clubs and flag", () => {
    const fixtures = fixturesAnswer(9, [
      [92, 3, 4, false],
      [91, 1, 2, true],
    ]);
    fixtures.push({ ...fixtures[0], id: 81, event: 8 });
    const document = liveDocument({
      live: liveAnswer([
        [7, 3, 90, 1, 0],
        [2, 0, 0],
      ]),
      fixtures,
      season: "2026-27",
      gameweek: 9,
      sourceTime: SOURCE_TIME,
    });
    assert.deepEqual(document, {
      contract_version: "week_live_v1",
      season: "2026-27",
      gameweek: 9,
      source_time: SOURCE_TIME,
      fixtures: [
        { id: 91, home_club: 1, away_club: 2, finished: true },
        { id: 92, home_club: 3, away_club: 4, finished: false },
      ],
      elements: [
        { element_id: 2, points: 0, minutes: 0, card_shown: false },
        { element_id: 7, points: 3, minutes: 90, card_shown: true },
      ],
    });
  });

  it("refuses a missing card count, a repeated element and a repeated fixture", () => {
    const live = liveAnswer([[7, 3, 90]]);
    delete live.elements[0].stats.red_cards;
    const args = { fixtures: [], season: "2026-27", gameweek: 9, sourceTime: SOURCE_TIME };
    assert.throws(() => liveDocument({ ...args, live }), /red_cards/);
    assert.throws(
      () =>
        liveDocument({
          ...args,
          live: liveAnswer([
            [7, 3, 90],
            [7, 1, 10],
          ]),
        }),
      /appears twice/,
    );
    const twice = fixturesAnswer(9, [
      [91, 1, 2, true],
      [91, 1, 2, true],
    ]);
    assert.throws(() => fixturesPart(twice, 9), /appears twice/);
  });
});
