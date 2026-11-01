// Synthetic FPL-shaped answers and in-memory stand-ins for the Worker's fetch, cache and clock.
//
// Every value here is invented: no member capture is used. Each answer carries fields the
// forwarder must drop, holding the text RAW-MARKER, so a test can show that nothing of FPL's
// own JSON beyond the trimmed fields leaves the Worker.

import { FPL_API, SCHEDULE_URL, upstreamPaths } from "../src/proxy.js";

export const SITE = "https://squadopt.mymandev.com";
export const SEASON = "2026-27";
export const MARKER = "RAW-MARKER";

const DAY_MS = 86_400_000;
const FIRST_DEADLINE_MS = Date.parse("2026-08-21T17:30:00Z");

/** Gameweek n's deadline: a week after the one before, from 21 August 2026. */
export const deadlineMs = (week) => FIRST_DEADLINE_MS + (week - 1) * 7 * DAY_MS;
export const deadlineText = (week) => new Date(deadlineMs(week)).toISOString().replace(".000", "");

/** Three days after gameweek 9's deadline: week 9 has started, week 10's deadline is ahead. */
export const NOW_MS = deadlineMs(9) + 3 * DAY_MS;

/** The site's fixture list, as fixtures_v1 publishes it, with no fixtures listed. */
export function fixturesJson({ weeks = 38 } = {}) {
  return {
    contract_version: "fixtures_v1",
    generated_at_utc: "2026-10-15T08:00:00Z",
    payload: {
      season: SEASON,
      source_snapshot_id: "synthetic",
      captured_at_utc: "2026-10-15T07:00:00Z",
      current_gameweek: 9,
      unscheduled_count: 0,
      gameweeks: Array.from({ length: weeks }, (_, index) => ({
        gameweek: index + 1,
        deadline_utc: deadlineText(index + 1),
        fixtures: [],
      })),
    },
  };
}

export const fpl = (path) => `${FPL_API}${path}`;

/** A clock a test can move. */
export function testClock(start = NOW_MS) {
  let at = start;
  return {
    now: () => at,
    advance: (ms) => {
      at += ms;
    },
    set: (ms) => {
      at = ms;
    },
  };
}

/** A data centre's cache as the Worker uses it: match and put by URL, honouring max-age. */
export function memoryCache(clock) {
  const stored = new Map();
  return {
    stored,
    async match(request) {
      const hit = stored.get(new Request(request).url);
      if (hit === undefined || clock.now() >= hit.expiresMs) return undefined;
      return new Response(hit.text, { status: hit.status, headers: hit.headers });
    },
    async put(request, response) {
      const control = response.headers.get("cache-control") ?? "";
      const maxAge = /^max-age=(\d+)$/.exec(control);
      const seconds = maxAge === null ? 0 : Number(maxAge[1]);
      stored.set(new Request(request).url, {
        text: await response.text(),
        status: response.status,
        headers: Object.fromEntries(response.headers),
        maxAge: seconds,
        expiresMs: clock.now() + seconds * 1000,
      });
    },
  };
}

/**
 * A fetch that answers from `answers`, a map of URL to a value, a Response, an Error to throw,
 * or a function returning one of those. Any other URL fails the test. Calls are recorded.
 */
export function fakeFetch(answers) {
  const calls = [];
  const fetchImpl = async (input, init) => {
    const url = String(input);
    calls.push({ url, init });
    if (!Object.hasOwn(answers, url)) throw new Error(`unexpected request to ${url}`);
    const entry = answers[url];
    const value = typeof entry === "function" ? entry() : entry;
    if (value instanceof Error) throw value;
    if (value instanceof Response) return value;
    return Response.json(value);
  };
  return { calls, fetchImpl, answers };
}

export const status =
  (code, text = "") =>
  () =>
    new Response(text, { status: code });

// Classic standings.

export function standingsPage({ league = 314, page = 1, hasNext = false, rows = 3 } = {}) {
  return {
    last_updated_data: "2026-10-19T09:00:00Z",
    raw_only: `${MARKER}-standings-root`,
    league: { id: league, name: "Synthetic League", raw_only: `${MARKER}-league` },
    standings: {
      has_next: hasNext,
      page,
      results: Array.from({ length: rows }, (_, index) => {
        const rank = (page - 1) * 50 + index + 1;
        return {
          entry: 5000 + rank,
          entry_name: `Example Team ${rank}`,
          player_name: `Example Manager ${rank}`,
          rank,
          rank_sort: rank,
          last_rank: index === 0 ? null : rank + 1,
          total: 600 - index * 7,
          event_total: 40 + index,
          raw_only: `${MARKER}-standing`,
        };
      }),
    },
  };
}

// One entry's documents.

export function entryAnswer(id, { name = "Synthetic XI", started = 1 } = {}) {
  return { id, name, started_event: started, raw_only: `${MARKER}-entry`, extra: { note: MARKER } };
}

export function historyAnswer({ weeks, chips = [], transfers = {}, costs = {}, bank = 5 }) {
  return {
    current: weeks.map((event) => ({
      event,
      points: 50 + event,
      event_transfers: transfers[event] ?? 0,
      event_transfers_cost: costs[event] ?? 0,
      bank,
      value: 1000 + event,
      raw_only: `${MARKER}-history-row`,
    })),
    past: [{ raw_only: `${MARKER}-past` }],
    chips: chips.map(({ name, event }) => ({ name, event, raw_only: `${MARKER}-chip` })),
  };
}

export function transfersAnswer(entry, rows) {
  return rows.map(([event, elementIn, elementOut, day]) => ({
    entry,
    event,
    time: new Date(deadlineMs(event - 1) + day * DAY_MS).toISOString(),
    element_in: elementIn,
    element_in_cost: 55,
    element_out: elementOut,
    element_out_cost: 55,
    raw_only: `${MARKER}-transfer`,
  }));
}

/**
 * One picks answer. `named` is the fifteen as named at the deadline; each substitution in
 * `subs` is applied to the positions as FPL applies it, unless `keepNamed` is set.
 */
export function picksAnswer(entry, week, options) {
  const {
    named,
    captain,
    vice,
    chip = null,
    subs = [],
    keepNamed = false,
    cost = 0,
    points = 61,
    bank = 5,
    value = 1003,
  } = options;
  const position = new Map(named.map((element, index) => [element, index + 1]));
  if (!keepNamed) {
    for (const [outgoing, incoming] of subs) {
      const out = position.get(outgoing);
      position.set(outgoing, position.get(incoming));
      position.set(incoming, out);
    }
  }
  const multiplier = (element) => {
    if (element === captain) return chip === "3xc" ? 3 : 2;
    return position.get(element) <= 11 || chip === "bboost" ? 1 : 0;
  };
  return {
    active_chip: chip,
    automatic_subs: subs.map(([outgoing, incoming]) => ({
      entry,
      element_in: incoming,
      element_out: outgoing,
      event: week,
      raw_only: `${MARKER}-sub`,
    })),
    entry_history: {
      event: week,
      points,
      total_points: 500,
      rank: 1234,
      bank,
      value,
      event_transfers: 1,
      event_transfers_cost: cost,
      points_on_bench: 4,
      raw_only: `${MARKER}-entry-history`,
    },
    picks: [...position]
      .sort((left, right) => left[1] - right[1])
      .map(([element, at]) => ({
        element,
        position: at,
        multiplier: multiplier(element),
        is_captain: element === captain,
        is_vice_captain: element === vice,
        raw_only: `${MARKER}-pick`,
      })),
  };
}

export const fifteen = (base) => Array.from({ length: 15 }, (_, index) => base + index + 1);

// One gameweek's live points and fixtures.

export function liveAnswer(elements) {
  return {
    elements: elements.map(([id, points, minutes, yellow = 0, red = 0]) => ({
      id,
      stats: {
        minutes,
        total_points: points,
        yellow_cards: yellow,
        red_cards: red,
        bps: 12,
        influence: `${MARKER}-influence`,
      },
      raw_extra: [{ raw_only: `${MARKER}-explain` }],
    })),
  };
}

export function fixturesAnswer(week, rows) {
  return rows.map(([id, home, away, finished]) => ({
    id,
    event: week,
    team_h: home,
    team_a: away,
    finished,
    kickoff_time: deadlineText(week),
    team_h_score: finished ? 1 : null,
    team_a_score: finished ? 0 : null,
    raw_only: `${MARKER}-fixture`,
  }));
}

// The two synthetic entries of the bundle examples.

/** Entry 101 opened the season, played a Wildcard in week 4 and its Free Hit in week 9. */
export const OPENER = 101;
/** Entry 202 joined in week 4; in week 9 an automatic substitution replaced its third pick. */
export const LATE = 202;

export const WEEK9_FIXTURES = [
  [91, 1, 2, true],
  [92, 3, 4, true],
  [93, 5, 6, true],
];

/** The URLs a bundle for table gameweek 10 reads, with their synthetic answers. */
export function bundleWorld({ week9Fixtures = WEEK9_FIXTURES } = {}) {
  const opening = fifteen(100);
  const held = [...opening.slice(0, 13), 120, 121];
  const freeHit = fifteen(300);
  const late = fifteen(200);
  return {
    [SCHEDULE_URL]: fixturesJson(),
    [fpl(upstreamPaths.fixtures(9))]: fixturesAnswer(9, week9Fixtures),

    [fpl(upstreamPaths.entry(OPENER))]: entryAnswer(OPENER),
    [fpl(upstreamPaths.history(OPENER))]: historyAnswer({
      weeks: [1, 2, 3, 4, 5, 6, 7, 8, 9],
      chips: [
        { name: "wildcard", event: 4 },
        { name: "freehit", event: 9 },
      ],
      transfers: { 2: 1, 5: 1, 9: 1 },
    }),
    [fpl(upstreamPaths.transfers(OPENER))]: transfersAnswer(OPENER, [
      [2, 120, 114, 2],
      [5, 121, 115, 1],
      [9, 301, 101, 1],
    ]),
    [fpl(upstreamPaths.picks(OPENER, 1))]: picksAnswer(OPENER, 1, {
      named: opening,
      captain: 110,
      vice: 111,
      bank: 0,
      value: 1000,
    }),
    [fpl(upstreamPaths.picks(OPENER, 8))]: picksAnswer(OPENER, 8, {
      named: held,
      captain: 110,
      vice: 111,
    }),
    [fpl(upstreamPaths.picks(OPENER, 9))]: picksAnswer(OPENER, 9, {
      named: freeHit,
      captain: 305,
      vice: 306,
      chip: "freehit",
      points: 72,
    }),

    [fpl(upstreamPaths.entry(LATE))]: entryAnswer(LATE, { name: "Late Synthetic", started: 4 }),
    [fpl(upstreamPaths.history(LATE))]: historyAnswer({
      weeks: [4, 5, 6, 7, 8, 9],
      transfers: { 6: 1, 9: 1 },
      costs: { 9: 4 },
    }),
    [fpl(upstreamPaths.transfers(LATE))]: transfersAnswer(LATE, [
      [6, 220, 215, 2],
      [9, 214, 216, 1],
    ]),
    [fpl(upstreamPaths.picks(LATE, 9))]: picksAnswer(LATE, 9, {
      named: [...late.slice(0, 14), 220],
      captain: 205,
      vice: 206,
      subs: [[203, 213]],
      cost: 4,
      points: 47,
    }),
  };
}

/** The URLs a live request for gameweek 9 reads. */
export function liveWorld({ fixtures = WEEK9_FIXTURES } = {}) {
  return {
    [SCHEDULE_URL]: fixturesJson(),
    [fpl(upstreamPaths.fixtures(9))]: fixturesAnswer(9, fixtures),
    [fpl(upstreamPaths.live(9))]: liveAnswer([
      [3, 2, 90],
      [1, 6, 90, 1],
      [2, 0, 0],
      [4, -1, 45, 0, 1],
      [5, 1, 0, 1],
    ]),
  };
}
