// The usage record's rules, as plain functions with no I/O: what an event may say and how it
// is laid out in the dataset. worker.js applies them; the report script reads the layout.
//
// Every field but the session is a word from a closed list. That is the privacy rule in code:
// a page cannot send an address, an entry number or a name, because none of them is a word
// here, and the session is random text of a fixed shape.
//
// Version 2 events (clicks, scrolling, speed, errors and arrivals) keep that rule: their text
// fields are words from closed lists too, and their numbers are integers in fixed ranges, so no
// pixel position, message or address fits in them.
//
// See docs/architecture/decisions/0014-usage-measurement.md and 0015-behaviour-measurement.md.

/** The one site whose pages may send events. */
export const SITE_ORIGIN = "https://squadopt.mymandev.com";

/** Every answer carries this header, so a client can tell the Worker from the site's shell. */
export const MARKER_HEADER = "x-squadopt-usage";
export const MARKER_VALUE = "1";

/**
 * The status answer's name, and the event versions the Worker takes. `EVENT_VERSION` is the
 * first one, which the status answer has always named as `event_version`; the answer lists
 * every version beside it rather than changing what that field means to an older reader.
 */
export const STATUS_CONTRACT = "usage_status_v1";
export const EVENT_VERSION = 1;
export const BEHAVIOUR_VERSION = 2;
export const EVENT_VERSIONS = [EVENT_VERSION, BEHAVIOUR_VERSION];

/** The Analytics Engine dataset, as wrangler.toml binds it. */
export const DATASET = "squadopt_usage";

/** A request body larger than this is refused before it is parsed. */
export const MAX_BODY_BYTES = 512;

/** The kinds of page, never the address: no league or entry number can be one of these. */
export const PAGES = new Set([
  "entry",
  "league",
  "members",
  "member",
  "history",
  "vs",
  "live",
  "reminder",
  "team",
  "fixtures",
  "contribute",
  "llmopt",
  "other",
]);

/** What a member page was showing; empty on the pages that have no tool. */
export const TOOLS = new Set([
  "",
  "week",
  "current-squad",
  "what-if",
  "duel",
  "chips",
  "card",
  "history",
  "vs",
  "live",
  "fixtures",
  "llmopt",
]);

/**
 * `open` is an address the router reached, `tool` a page drawn past its gates, the two picker
 * steps are the member picker shown and a name taken in it, `device_solve` a plan started in
 * the visitor's browser.
 */
export const STEPS = new Set(["open", "tool", "picker_shown", "picker_claimed", "device_solve"]);

export const LANGUAGES = new Set(["tr", "en"]);

/** The class of device, worked out in the browser; the measurements behind it are not sent. */
export const DEVICES = new Set(["phone", "tablet", "desktop", "unknown"]);

/** A per-tab random token: eight random bytes in hexadecimal. */
export const SESSION = /^[0-9a-f]{16}$/;

const FIELDS = ["device", "lang", "page", "session", "step", "tool", "v"];

/** The dataset's text columns in order: `blob1` is the first of these, and so on. */
export const BLOB_COLUMNS = ["page", "tool", "step", "lang", "device", "session"];

// Version 2 (ADR 0015). Every list below is closed: a word the Worker does not know is refused.

/** What a version 2 event tells. */
export const KINDS = new Set(["click", "scroll", "vital", "error", "arrival"]);

/**
 * The part of a page a click landed in, from the nearest `data-zone` around it; `page` when
 * there is none, so a component without a zone still counts.
 *
 * A word is never taken out: `nav` (the whole sidebar, as tall as the window) and `llmopt` (the
 * whole LLMOPT page) are no longer placed on any element since 2026-11-23, when smaller zones
 * replaced them, but an older tab still sends them and the record keeps their rows. The same
 * holds since 2026-11-23 for the whole-page words `history`, `vs`, `live`, `reminder`, `fixtures`
 * and `contribute`, each split into the parts of its page.
 */
export const ZONES = new Set([
  "nav",
  "nav-brand",
  "nav-member",
  "nav-links",
  "nav-settings",
  "phone-bar",
  "topbar",
  "entry-form",
  "league-list",
  "fpl-id-help",
  "member-table",
  "member-picker",
  "decision",
  "pitch",
  "squad",
  "fixtures-rail",
  "tool-tabs",
  "chip-timing",
  "chip-choice",
  "preferences",
  "advice-request",
  "advice-details",
  "what-if",
  "duel",
  "last-week",
  "apply-fpl",
  "resources",
  "coach-news",
  "new-information",
  "history",
  "history-header",
  "history-report",
  "history-picker",
  "history-table",
  "history-week",
  "vs",
  "vs-header",
  "vs-weeks",
  "vs-score",
  "vs-sides",
  "vs-why",
  "vs-squad",
  "live",
  "live-header",
  "live-score",
  "live-refresh",
  "live-rival",
  "live-differentials",
  "live-recap",
  "live-players",
  "llmopt",
  "llmopt-model",
  "llmopt-instructions",
  "llmopt-rule-list",
  "llmopt-rules",
  "llmopt-plan",
  "llmopt-compute",
  "llmopt-results",
  "reminder",
  "reminder-header",
  "reminder-switch",
  "reminder-steps",
  "fixtures",
  "fixtures-header",
  "fixtures-view",
  "fixtures-clubs",
  "fixtures-team",
  "fixtures-matrix",
  "contribute",
  "contribute-header",
  "contribute-team",
  "contribute-position",
  "contribute-player",
  "contribute-form",
  "contribute-comments",
  "page",
]);

/** Whether a click was on something that acts (a link, a button, a field) or on plain content. */
export const TARGETS = new Set(["control", "plain"]);

/** A click on its own, the burst of a frustrated visitor, or a click that changed nothing. */
export const MARKS = new Set(["none", "rage", "dead"]);

/** How long a page view lasted, as a bucket: the timestamps behind it are not sent. */
export const DWELLS = new Set(["s5", "s15", "s30", "s60", "s180", "s600", "long"]);

/** The browser's speed measurements, and the rating its thresholds give each. */
export const METRICS = new Set(["lcp", "inp", "cls", "fcp", "ttfb"]);
export const RATINGS = new Set(["good", "needs", "poor"]);

/** The kind of uncaught failure; its message and stack are never sent. */
export const ERRORS = new Set(["script", "promise", "chunk"]);

/** Where a visit came from, matched in the browser; the referrer's address is never sent. */
export const SOURCES = new Set([
  "direct",
  "internal",
  "whatsapp",
  "telegram",
  "google",
  "bing",
  "x",
  "instagram",
  "facebook",
  "reddit",
  "fpl",
  "other",
]);

/** How long since this browser's last visit, as a bucket worked out from one stored ISO week. */
export const VISITS = new Set(["new", "same_week", "last_week", "weeks_2_4", "older", "unknown"]);

/** A click's cell is in a grid this many cells square over its zone: row times 20 plus column. */
export const GRID = 20;

/**
 * A version 2 event's fields beside the common ones, and where they go in the dataset: up to
 * three words in `blob7` to `blob9`, in this order, and at most one number in `double2`.
 */
export const KIND_LAYOUT = {
  click: { words: ["zone", "target", "mark"], number: "cell" },
  scroll: { words: ["dwell"], number: "depth" },
  vital: { words: ["metric", "rating"], number: "value" },
  error: { words: ["error"], number: null },
  arrival: { words: ["source", "visit"], number: null },
};

/** How many text columns version 2 adds after version 1's six: `blob7` to `blob9`. */
export const DETAIL_COLUMNS = 3;

/** The fields every version 2 event carries: version 1's but `step`, and the kind. */
const COMMON_V2 = ["device", "kind", "lang", "page", "session", "tool", "v"];

const WORD_LISTS = {
  zone: ZONES,
  target: TARGETS,
  mark: MARKS,
  dwell: DWELLS,
  metric: METRICS,
  rating: RATINGS,
  error: ERRORS,
  source: SOURCES,
  visit: VISITS,
};

/** The integer ranges, both ends included, with the step a value must be a multiple of. */
export const NUMBER_RANGES = {
  cell: { min: 0, max: GRID * GRID - 1, step: 1 },
  depth: { min: 0, max: 100, step: 10 },
  value: { min: 0, max: 60_000, step: 1 },
};

export class RefusedError extends Error {
  constructor(reason) {
    super(reason);
    this.name = "RefusedError";
    this.reason = reason;
  }
}

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

function word(set, value, reason) {
  if (typeof value !== "string" || !set.has(value)) throw new RefusedError(reason);
  return value;
}

/** An integer in its range and on its step; a fraction, text or a boolean is refused. */
function integer({ min, max, step }, value, reason) {
  if (!Number.isInteger(value) || value < min || value > max || value % step !== 0) {
    throw new RefusedError(reason);
  }
  return value;
}

function checkSession(value) {
  if (typeof value !== "string" || !SESSION.test(value)) throw new RefusedError("session_refused");
}

/**
 * The event a request carries, or a refusal naming the first thing wrong with it. The version
 * decides which rules apply, so a version neither set of rules knows is refused first.
 */
export function eventFrom(body) {
  if (!isObject(body)) throw new RefusedError("body_not_object");
  if (body.v === EVENT_VERSION) return stepEvent(body);
  if (body.v === BEHAVIOUR_VERSION) return behaviourEvent(body);
  throw new RefusedError("wrong_version");
}

/**
 * A version 1 event: exactly the seven fields, nothing beside them, so a page that started
 * sending more would be refused rather than quietly trimmed.
 */
function stepEvent(body) {
  if (Object.keys(body).sort().join() !== FIELDS.join()) throw new RefusedError("wrong_fields");
  checkSession(body.session);
  return {
    page: word(PAGES, body.page, "page_refused"),
    tool: word(TOOLS, body.tool, "tool_refused"),
    step: word(STEPS, body.step, "step_refused"),
    lang: word(LANGUAGES, body.lang, "lang_refused"),
    device: word(DEVICES, body.device, "device_refused"),
    session: body.session,
    v: body.v,
  };
}

/**
 * A version 2 event: the common fields and exactly its kind's, nothing beside them. The kind
 * is read first because it decides which fields are right.
 */
function behaviourEvent(body) {
  if (!Object.hasOwn(body, "kind")) throw new RefusedError("wrong_fields");
  const kind = word(KINDS, body.kind, "kind_refused");
  const { words, number } = KIND_LAYOUT[kind];
  const expected = [...COMMON_V2, ...words, ...(number === null ? [] : [number])].sort();
  if (Object.keys(body).sort().join() !== expected.join()) throw new RefusedError("wrong_fields");
  checkSession(body.session);
  const event = {
    page: word(PAGES, body.page, "page_refused"),
    tool: word(TOOLS, body.tool, "tool_refused"),
    kind,
    lang: word(LANGUAGES, body.lang, "lang_refused"),
    device: word(DEVICES, body.device, "device_refused"),
    session: body.session,
    v: body.v,
  };
  for (const field of words) event[field] = word(WORD_LISTS[field], body[field], `${field}_refused`);
  if (number !== null) event[number] = integer(NUMBER_RANGES[number], body[number], `${number}_refused`);
  return event;
}

/**
 * The event as one Analytics Engine data point. The session is the index because the dataset
 * samples by index under heavy load, and a visit is only useful with its steps together.
 */
export function dataPoint(event) {
  if (event.v === EVENT_VERSION) {
    return {
      indexes: [event.session],
      blobs: BLOB_COLUMNS.map((column) => event[column]),
      doubles: [event.v],
    };
  }
  // Version 2 keeps version 1's six columns with the kind where the step was, and pads its own
  // words to three, so a column always holds the same field for a given kind.
  const { words, number } = KIND_LAYOUT[event.kind];
  const details = words.map((field) => event[field]);
  while (details.length < DETAIL_COLUMNS) details.push("");
  return {
    indexes: [event.session],
    blobs: [event.page, event.tool, event.kind, event.lang, event.device, event.session, ...details],
    doubles: [event.v, number === null ? 0 : event[number]],
  };
}
