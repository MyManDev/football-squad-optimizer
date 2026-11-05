// What the FPL forwarder answers, what it keeps of FPL's answers, and how long it keeps them.
//
// Nothing here touches the network, the clock or the cache: worker.js does the fetching and the
// caching and hands each answer to this module as plain data, so every rule about which request
// is allowed, which field leaves the Worker and how long a copy lives can be tested under
// node --test. The decision is ADR 0012 (docs/architecture/decisions/0012-fpl-forwarder.md); the
// documents are fpl_league_standings_v1, fpl_entry_bundle_v1 and week_live_v1 in docs/contracts.

/** The user agent the capture sends (USER_AGENT in src/squadopt/platform/fpl_capture.py). */
export const USER_AGENT = "squadopt/1.0 (private research; contact via repository owner)";

/** FPL's API root, as BASE_URL in src/squadopt/platform/fpl_capture.py, with its slash. */
export const FPL_API = "https://fantasy.premierleague.com/api/";

/** The site the Worker sits in front of. Its fixture list says which week is current. */
export const SITE_ORIGIN = "https://squadopt.mymandev.com";
export const SCHEDULE_URL = `${SITE_ORIGIN}/data/fixtures.json`;

/** Every answer carries this header, so a client can tell the Worker from the site's shell. */
export const MARKER_HEADER = "x-squadopt-fpl";
export const MARKER_VALUE = "1";

/** Says whether a document was read just now, is this data centre's copy, or the last good one. */
export const CACHE_HEADER = "x-squadopt-fpl-cache";

export const STANDINGS_CONTRACT = "fpl_league_standings_v1";
export const BUNDLE_CONTRACT = "fpl_entry_bundle_v1";
export const LIVE_CONTRACT = "week_live_v1";

/** A classic league page beyond this is refused: the device reads leagues of up to 1,000. */
export const MAX_STANDINGS_PAGE = 20;
export const LAST_GAMEWEEK = 38;

/** The chips week_live_v1's member block names; any other chip leaves that block out. */
export const MEMBER_WEEK_CHIPS = Object.freeze(["3xc", "bboost", "freehit", "wildcard"]);

/** One request to FPL or to the site gives up after this long. */
export const UPSTREAM_TIMEOUT_MS = 10_000;

/** A standings page is kept for 10 minutes. */
export const STANDINGS_TTL_SECONDS = 600;
/** A week whose fixtures are not all finished is kept for 60 seconds. */
export const LIVE_PLAYING_TTL_SECONDS = 60;
/** A bundle whose current week is still being played is kept for 10 minutes. */
export const BUNDLE_PLAYING_TTL_SECONDS = 600;
/** A league or entry FPL does not have is remembered for 10 minutes. */
export const NOT_FOUND_TTL_SECONDS = 600;
/** The site's fixture list is read at most once every 5 minutes per data centre. */
export const SCHEDULE_TTL_SECONDS = 300;
/** After the season's last deadline, "until the next deadline" becomes one day. */
export const SEASON_END_TTL_SECONDS = 86_400;
/** No fresh copy outlives this, whatever the schedule says. */
export const MAX_TTL_SECONDS = 7 * 86_400;
/**
 * The last good copy of each document, served when FPL refuses or fails, outlives its fresh
 * copy by two days: it is only ever read once the fresh copy has gone.
 */
export const LAST_GOOD_EXTRA_SECONDS = 2 * 86_400;

/**
 * Cache keys live under this path of the site's host. The route sends the path to the Worker,
 * which answers it with 404, so a cached copy is only ever read through the Worker's own lookup.
 */
export const CACHE_PREFIX = "/api/v1/fpl/.cache/v1/";
export const SCHEDULE_CACHE_KEY = `${SITE_ORIGIN}${CACHE_PREFIX}schedule`;

const ID_TEXT = /^[1-9][0-9]{0,14}$/;
const SMALL_TEXT = /^[1-9][0-9]?$/;
const SEASON_TEXT = /^[0-9]{4}-[0-9]{2}$/;

const STANDINGS_PATH = /^\/api\/v1\/fpl\/standings\/([^/]+)$/;
const BUNDLE_PATH = /^\/api\/v1\/fpl\/entry\/([^/]+)\/bundle$/;
const LIVE_PATH = /^\/api\/v1\/fpl\/live\/([^/]+)$/;

/** A document from FPL or the site that does not have the shape this module reads. */
export class UnreadableError extends Error {
  constructor(message) {
    super(message);
    this.name = "UnreadableError";
  }
}

function notFound(detail) {
  return { status: 404, body: { error: "not_found", detail } };
}

function positiveId(text) {
  return ID_TEXT.test(text) ? Number(text) : null;
}

function smallNumber(text, maximum) {
  if (!SMALL_TEXT.test(text)) return null;
  const value = Number(text);
  return value <= maximum ? value : null;
}

/** The query must name exactly these parameters, each once, and nothing else. */
function onlyParameters(searchParams, names) {
  const keys = [...searchParams.keys()];
  if (keys.length !== names.length) return false;
  return names.every((name) => searchParams.getAll(name).length === 1);
}

/**
 * Which answer a request gets. A GET on one of the three routes, with its ids in range and its
 * query exactly as written, gives { kind, ... }. Any other method on those paths gives a 405
 * refusal; every other path, id or query gives a 404 refusal. Only the URL is read.
 *
 * - /api/v1/fpl/standings/{league}?page={1..20} gives { kind: "standings", league, page }
 * - /api/v1/fpl/entry/{entry}/bundle?gw={1..38} gives { kind: "bundle", entry, gameweek }
 * - /api/v1/fpl/live/{1..38} gives { kind: "live", gameweek }
 */
export function routeFor(method, url) {
  const { pathname, searchParams } = url;
  const standings = STANDINGS_PATH.exec(pathname);
  const bundle = BUNDLE_PATH.exec(pathname);
  const live = LIVE_PATH.exec(pathname);
  if (standings === null && bundle === null && live === null) {
    return notFound("the forwarder answers only its three routes");
  }
  if (method !== "GET") {
    return {
      status: 405,
      body: { error: "method_not_allowed", detail: "the forwarder answers GET only" },
    };
  }
  if (standings !== null) {
    const league = positiveId(standings[1]);
    if (league === null) return notFound("a league id is a positive integer");
    if (!onlyParameters(searchParams, ["page"])) {
      return notFound("standings take one query parameter, page");
    }
    const page = smallNumber(searchParams.get("page"), MAX_STANDINGS_PAGE);
    if (page === null) return notFound(`page is a whole number from 1 to ${MAX_STANDINGS_PAGE}`);
    return { kind: "standings", league, page };
  }
  if (bundle !== null) {
    const entry = positiveId(bundle[1]);
    if (entry === null) return notFound("an entry id is a positive integer");
    if (!onlyParameters(searchParams, ["gw"])) {
      return notFound("a bundle takes one query parameter, gw");
    }
    const gameweek = smallNumber(searchParams.get("gw"), LAST_GAMEWEEK);
    if (gameweek === null) return notFound(`gw is a whole number from 1 to ${LAST_GAMEWEEK}`);
    return { kind: "bundle", entry, gameweek };
  }
  const gameweek = smallNumber(live[1], LAST_GAMEWEEK);
  if (gameweek === null) return notFound(`a gameweek is a whole number from 1 to ${LAST_GAMEWEEK}`);
  if (!onlyParameters(searchParams, [])) return notFound("a live week takes no query parameters");
  return { kind: "live", gameweek };
}

/** The two cache keys of a route: its fresh copy and its last good copy. */
export function cacheKeys(route) {
  let tail;
  if (route.kind === "standings") tail = `standings/${route.league}/${route.page}`;
  else if (route.kind === "bundle") tail = `bundle/${route.entry}/${route.gameweek}`;
  else if (route.kind === "live") tail = `live/${route.gameweek}`;
  else throw new TypeError(`no cache keys for a route of kind ${String(route.kind)}`);
  return {
    fresh: `${SITE_ORIGIN}${CACHE_PREFIX}fresh/${tail}`,
    lastGood: `${SITE_ORIGIN}${CACHE_PREFIX}last-good/${tail}`,
  };
}

/** The FPL paths the forwarder reads, relative to FPL_API. Nothing else is ever asked. */
export const upstreamPaths = Object.freeze({
  classicStandings: (league, page) => `leagues-classic/${league}/standings/?page_standings=${page}`,
  headToHeadStandings: (league) => `leagues-h2h/${league}/standings/`,
  entry: (entry) => `entry/${entry}/`,
  history: (entry) => `entry/${entry}/history/`,
  transfers: (entry) => `entry/${entry}/transfers/`,
  picks: (entry, gameweek) => `entry/${entry}/event/${gameweek}/picks/`,
  live: (gameweek) => `event/${gameweek}/live/`,
  fixtures: (gameweek) => `fixtures/?event=${gameweek}`,
});

// Readers. Each one takes a parsed JSON value and returns only the fields named, or throws
// UnreadableError naming the first field that is not what the documents say it is.

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function object(value, field) {
  if (!isObject(value)) throw new UnreadableError(`${field} is not an object`);
  return value;
}

function array(value, field) {
  if (!Array.isArray(value)) throw new UnreadableError(`${field} is not an array`);
  return value;
}

function integer(value, field, minimum = Number.MIN_SAFE_INTEGER) {
  if (!Number.isSafeInteger(value) || value < minimum) {
    throw new UnreadableError(`${field} is not an integer of at least ${minimum}`);
  }
  return value;
}

function week(value, field) {
  const read = integer(value, field, 1);
  if (read > LAST_GAMEWEEK) throw new UnreadableError(`${field} is after gameweek 38`);
  return read;
}

function text(value, field) {
  if (typeof value !== "string") throw new UnreadableError(`${field} is not text`);
  return value;
}

function flag(value, field) {
  if (typeof value !== "boolean") throw new UnreadableError(`${field} is not a boolean`);
  return value;
}

function utcTime(value, field) {
  const read = text(value, field);
  if (!Number.isFinite(Date.parse(read))) throw new UnreadableError(`${field} is not a time`);
  return read;
}

function byNumber(field) {
  return (left, right) => left[field] - right[field];
}

function refuseRepeats(rows, field, what) {
  const seen = new Set();
  for (const row of rows) {
    if (seen.has(row[field])) throw new UnreadableError(`${what} ${row[field]} appears twice`);
    seen.add(row[field]);
  }
  return rows;
}

/**
 * The site's own fixture list (fixtures_v1, /data/fixtures.json) as the schedule the Worker
 * needs: the season and each gameweek's deadline. Fixtures, teams and scores are not kept.
 */
export function scheduleFrom(document) {
  const root = object(document, "fixtures.json");
  if (root.contract_version !== "fixtures_v1") {
    throw new UnreadableError("fixtures.json is not a fixtures_v1 document");
  }
  const payload = object(root.payload, "fixtures.json payload");
  const season = text(payload.season, "payload.season");
  if (!SEASON_TEXT.test(season)) throw new UnreadableError("payload.season is not like 2026-27");
  const deadlines = array(payload.gameweeks, "payload.gameweeks")
    .map((value) => {
      const row = object(value, "payload gameweek");
      return {
        gameweek: week(row.gameweek, "gameweek"),
        deadline_utc: utcTime(row.deadline_utc, "deadline_utc"),
      };
    })
    .sort(byNumber("gameweek"));
  if (deadlines.length === 0) throw new UnreadableError("fixtures.json names no gameweek");
  refuseRepeats(deadlines, "gameweek", "gameweek");
  for (let index = 1; index < deadlines.length; index += 1) {
    const before = Date.parse(deadlines[index - 1].deadline_utc);
    if (Date.parse(deadlines[index].deadline_utc) <= before) {
      throw new UnreadableError("fixtures.json deadlines do not rise with the gameweek");
    }
  }
  return { season, deadlines };
}

/**
 * Where the season stands at `nowMs`: the latest gameweek whose deadline has passed (0 before
 * the first deadline) and the next deadline still ahead (null after the last one). A deadline
 * at exactly `nowMs` has passed, as the capture's next_open_deadline reads it.
 */
export function weekState(schedule, nowMs) {
  let latestStarted = 0;
  let nextDeadlineMs = null;
  for (const { gameweek, deadline_utc: deadline } of schedule.deadlines) {
    const at = Date.parse(deadline);
    if (at <= nowMs) latestStarted = Math.max(latestStarted, gameweek);
    else if (nextDeadlineMs === null || at < nextDeadlineMs) nextDeadlineMs = at;
  }
  return { latestStarted, nextDeadlineMs };
}

/**
 * Whether a bundle may be asked for table gameweek `gameweek`: its picks are those of the week
 * before, so that week's deadline must have passed. The table gameweek is therefore from 2 to
 * the week after the latest started one, which is the week fixtures.json calls current.
 */
export function bundleWeekAllowed(gameweek, latestStarted) {
  return gameweek >= 2 && gameweek <= Math.min(LAST_GAMEWEEK, latestStarted + 1);
}

/** Whether a live week may be asked for: the current week or an earlier one. */
export function liveWeekAllowed(gameweek, latestStarted) {
  return gameweek >= 1 && gameweek <= latestStarted;
}

function clampTtl(seconds) {
  return Math.max(0, Math.min(MAX_TTL_SECONDS, Math.floor(seconds)));
}

/** Seconds until the next deadline, or a day once the season's last deadline has passed. */
export function untilNextDeadline(nowMs, nextDeadlineMs) {
  if (nextDeadlineMs === null) return SEASON_END_TTL_SECONDS;
  return clampTtl((nextDeadlineMs - nowMs) / 1000);
}

/** How long the last good copy of a document kept fresh for `freshSeconds` lives. */
export function lastGoodTtl(freshSeconds) {
  return Math.max(0, freshSeconds) + LAST_GOOD_EXTRA_SECONDS;
}

/** A week is finished when it has fixtures and every one of them is finished. */
export function weekFinished(fixtures) {
  return fixtures.length > 0 && fixtures.every((fixture) => fixture.finished === true);
}

/** A live week: 60 seconds while it is played, until the next deadline once it is finished. */
export function liveTtl({ finished, nowMs, nextDeadlineMs }) {
  return finished ? untilNextDeadline(nowMs, nextDeadlineMs) : LIVE_PLAYING_TTL_SECONDS;
}

/**
 * A bundle: until the next deadline once the current week is finished, 10 minutes while it is
 * still played (its points and automatic substitutions still move), and never past the next
 * deadline, when the picks it should hold change.
 */
export function bundleTtl({ settled, nowMs, nextDeadlineMs }) {
  const bound = untilNextDeadline(nowMs, nextDeadlineMs);
  return settled ? bound : Math.min(BUNDLE_PLAYING_TTL_SECONDS, bound);
}

/**
 * One classic standings page (leagues-classic/{id}/standings/?page_standings=N) trimmed to
 * fpl_league_standings_v1. The page must declare the league and the page asked for.
 */
export function standingsDocument(raw, { league, page, sourceTime }) {
  const document = object(raw, "standings");
  const declared = object(document.league, "standings.league");
  if (integer(declared.id, "league.id", 1) !== league) {
    throw new UnreadableError(`the standings page does not declare league ${league}`);
  }
  const section = object(document.standings, "standings.standings");
  if (integer(section.page, "standings.page", 1) !== page) {
    throw new UnreadableError(`the standings answer is not page ${page}`);
  }
  const results = array(section.results, "standings.results").map((value) => {
    const row = object(value, "standing");
    return {
      entry: integer(row.entry, "standing.entry", 1),
      entry_name: text(row.entry_name, "standing.entry_name"),
      player_name: text(row.player_name, "standing.player_name"),
      rank: integer(row.rank, "standing.rank", 0),
      rank_sort: integer(row.rank_sort, "standing.rank_sort", 1),
      last_rank: row.last_rank == null ? null : integer(row.last_rank, "standing.last_rank", 0),
      total: integer(row.total, "standing.total"),
      event_total: integer(row.event_total, "standing.event_total"),
    };
  });
  refuseRepeats(results, "entry", "entry");
  const updated = document.last_updated_data;
  return {
    contract_version: STANDINGS_CONTRACT,
    league: {
      id: league,
      name: typeof declared.name === "string" ? declared.name : null,
      scoring: "classic",
    },
    page,
    has_next: flag(section.has_next, "standings.has_next"),
    last_updated_data: typeof updated === "string" && updated.trim() !== "" ? updated : null,
    source_time: sourceTime,
    results,
  };
}

/** Whether a head-to-head standings answer declares this league, as the capture asks it. */
export function declaresLeague(raw, league) {
  return isObject(raw) && isObject(raw.league) && raw.league.id === league;
}

/** entry/{id}/: the identity, team name and joining week the entry reader takes. */
export function entryPart(raw, entry) {
  const document = object(raw, "entry");
  if (integer(document.id, "entry.id", 1) !== entry) {
    throw new UnreadableError(`the entry answer does not declare entry ${entry}`);
  }
  return {
    id: entry,
    name: text(document.name, "entry.name"),
    started_event: week(document.started_event, "entry.started_event"),
  };
}

/** entry/{id}/history/: each played week's transfers, cost and bank, and the chips played. */
export function historyPart(raw) {
  const document = object(raw, "history");
  const current = array(document.current, "history.current").map((value) => {
    const row = object(value, "history row");
    return {
      event: week(row.event, "history.event"),
      event_transfers: integer(row.event_transfers, "history.event_transfers", 0),
      event_transfers_cost: integer(row.event_transfers_cost, "history.event_transfers_cost", 0),
      bank: Number.isSafeInteger(row.bank) ? row.bank : null,
    };
  });
  const chips = array(document.chips, "history.chips").map((value) => {
    const row = object(value, "chip");
    return { name: text(row.name, "chip.name"), event: week(row.event, "chip.event") };
  });
  return { current, chips };
}

/** entry/{id}/transfers/: every transfer, with the prices the purchase-price replay reads. */
export function transfersPart(raw) {
  return array(raw, "transfers").map((value) => {
    const row = object(value, "transfer");
    return {
      entry: integer(row.entry, "transfer.entry", 1),
      event: week(row.event, "transfer.event"),
      time: utcTime(row.time, "transfer.time"),
      element_in: integer(row.element_in, "transfer.element_in", 1),
      element_in_cost: integer(row.element_in_cost, "transfer.element_in_cost", 0),
      element_out: integer(row.element_out, "transfer.element_out", 1),
      element_out_cost: integer(row.element_out_cost, "transfer.element_out_cost", 0),
    };
  });
}

/**
 * entry/{id}/event/{gw}/picks/ as the picks reader takes it: the fifteen in FPL's own order,
 * the automatic substitutions, the chip, and the week's bank and value. The answer must be for
 * the gameweek asked.
 */
export function picksPart(raw, gameweek) {
  const document = object(raw, "picks");
  const history = object(document.entry_history, "picks.entry_history");
  if (week(history.event, "picks.entry_history.event") !== gameweek) {
    throw new UnreadableError(`the picks answer is not for gameweek ${gameweek}`);
  }
  const substitutions = document.automatic_subs == null ? [] : document.automatic_subs;
  return {
    active_chip:
      document.active_chip == null ? null : text(document.active_chip, "picks.active_chip"),
    automatic_subs: array(substitutions, "picks.automatic_subs").map((value) => {
      const row = object(value, "automatic substitution");
      return {
        entry: integer(row.entry, "automatic_sub.entry", 1),
        event: week(row.event, "automatic_sub.event"),
        element_in: integer(row.element_in, "automatic_sub.element_in", 1),
        element_out: integer(row.element_out, "automatic_sub.element_out", 1),
      };
    }),
    entry_history: {
      event: gameweek,
      bank: integer(history.bank, "picks.entry_history.bank", 0),
      value: integer(history.value, "picks.entry_history.value", 0),
    },
    picks: array(document.picks, "picks.picks")
      .map((value) => {
        const row = object(value, "pick");
        return {
          element: integer(row.element, "pick.element", 1),
          position: integer(row.position, "pick.position", 1),
          multiplier: integer(row.multiplier, "pick.multiplier", 0),
          is_captain: flag(row.is_captain, "pick.is_captain"),
          is_vice_captain: flag(row.is_vice_captain, "pick.is_vice_captain"),
        };
      })
      .sort(byNumber("position")),
  };
}

/**
 * The positions as they were named at the deadline. FPL moves a substitute into the starter's
 * position when it applies an automatic substitution; some answers keep the named positions.
 * Each recorded substitution is undone the way the benchmark's _original_picks undoes it
 * (src/squadopt/experiments/benchmark_v2_live.py). Null when they cannot be undone.
 */
function namedOrder(picks, substitutions, entry, gameweek) {
  const position = new Map(picks.map((row) => [row.element, row.position]));
  const changed = new Set();
  for (const substitution of substitutions) {
    const { element_out: outgoing, element_in: incoming } = substitution;
    if (substitution.entry !== entry || substitution.event !== gameweek) return null;
    if (!position.has(outgoing) || !position.has(incoming)) return null;
    if (outgoing === incoming || changed.has(outgoing) || changed.has(incoming)) return null;
    changed.add(outgoing);
    changed.add(incoming);
    const out = position.get(outgoing);
    const into = position.get(incoming);
    if (out > 11 && into <= 11) {
      position.set(outgoing, into);
      position.set(incoming, out);
    } else if (!(out <= 11 && into > 11)) {
      return null;
    }
  }
  return [...position].sort((left, right) => left[1] - right[1]).map(([element]) => element);
}

/**
 * The in-progress member week of #980 comment 6409696721, in week_live_v1's memberWeek shape:
 * the named pick order, captain, vice, chip, event_transfers_cost and entry_history.points of
 * one picks answer. Null when that answer cannot be stated in that shape: a chip outside
 * week_live_v1's list, fifteen that are not fifteen distinct players in positions 1 to 15, no
 * single captain and different vice among the named eleven, substitutions that cannot be
 * undone, or no transfer cost.
 */
export function memberWeekFrom(raw, entry, gameweek) {
  const trimmed = picksPart(raw, gameweek);
  const history = raw.entry_history;
  const chip = trimmed.active_chip;
  if (chip !== null && !MEMBER_WEEK_CHIPS.includes(chip)) return null;
  const positions = trimmed.picks.map((row) => row.position);
  if (positions.length !== 15 || positions.some((value, index) => value !== index + 1)) {
    return null;
  }
  const order = namedOrder(trimmed.picks, trimmed.automatic_subs, entry, gameweek);
  if (order === null || new Set(order).size !== 15) return null;
  const captains = trimmed.picks.filter((row) => row.is_captain).map((row) => row.element);
  const vices = trimmed.picks.filter((row) => row.is_vice_captain).map((row) => row.element);
  if (captains.length !== 1 || vices.length !== 1 || captains[0] === vices[0]) return null;
  const eleven = order.slice(0, 11);
  if (!eleven.includes(captains[0]) || !eleven.includes(vices[0])) return null;
  const cost = history.event_transfers_cost;
  if (!Number.isSafeInteger(cost) || cost < 0) return null;
  return {
    entry_id: entry,
    gameweek,
    pick_order: order,
    captain: captains[0],
    vice: vices[0],
    active_chip: chip,
    transfer_cost: cost,
    ...(Number.isSafeInteger(history.points) ? { entry_history_points: history.points } : {}),
  };
}

/** Whether the Free Hit walk-back goes on past this week: FPL's Free Hit squad lasts a week. */
export function freeHitWeek(picks) {
  return picks.active_chip === "freehit";
}

/** Whether the purchase-price replay needs the gameweek 1 picks: the history starts there. */
export function opensAtGameweekOne(history) {
  return history.current.some((row) => row.event === 1);
}

/** The bundle document, from the parts the Worker read. `picks` maps a week to its picks. */
export function bundleDocument({ entry, gameweek, sourceTime, parts, picks, currentWeek }) {
  return {
    contract_version: BUNDLE_CONTRACT,
    entry_id: entry,
    gameweek,
    source_time: sourceTime,
    entry: parts.entry,
    history: parts.history,
    transfers: parts.transfers,
    picks: [...picks.entries()]
      .sort((left, right) => left[0] - right[0])
      .map(([, document]) => document),
    current_week: currentWeek,
  };
}

/** fixtures/?event={gw}: each of the week's fixtures with its clubs and finished flag. */
export function fixturesPart(raw, gameweek) {
  const rows = array(raw, "fixtures")
    .filter((value) => object(value, "fixture").event === gameweek)
    .map((row) => ({
      id: integer(row.id, "fixture.id", 1),
      home_club: integer(row.team_h, "fixture.team_h", 1),
      away_club: integer(row.team_a, "fixture.team_a", 1),
      finished: flag(row.finished, "fixture.finished"),
    }))
    .sort(byNumber("id"));
  return refuseRepeats(rows, "id", "fixture");
}

/**
 * event/{gw}/live/ and fixtures/?event={gw} trimmed to week_live_v1, without member blocks and
 * without positions or clubs: source A resolves those by element id (week_live_v1.md). A card
 * is either a yellow or a red; a missing card count is refused rather than read as none.
 */
export function liveDocument({ live, fixtures, season, gameweek, sourceTime }) {
  const document = object(live, "live");
  const elements = array(document.elements, "live.elements")
    .map((value) => {
      const row = object(value, "live element");
      const stats = object(row.stats, "live element stats");
      const yellow = integer(stats.yellow_cards, "stats.yellow_cards", 0);
      const red = integer(stats.red_cards, "stats.red_cards", 0);
      return {
        element_id: integer(row.id, "live element id", 1),
        points: integer(stats.total_points, "stats.total_points"),
        minutes: integer(stats.minutes, "stats.minutes", 0),
        card_shown: yellow > 0 || red > 0,
      };
    })
    .sort(byNumber("element_id"));
  refuseRepeats(elements, "element_id", "element");
  return {
    contract_version: LIVE_CONTRACT,
    season,
    gameweek,
    source_time: sourceTime,
    fixtures: fixturesPart(fixtures, gameweek),
    elements,
  };
}
