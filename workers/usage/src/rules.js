// The usage record's rules, as plain functions with no I/O: what an event may say and how it
// is laid out in the dataset. worker.js applies them; the report script reads the layout.
//
// Every field but the session is a word from a closed list. That is the privacy rule in code:
// a page cannot send an address, an entry number or a name, because none of them is a word
// here, and the session is random text of a fixed shape.
//
// See docs/architecture/decisions/0014-usage-measurement.md.

/** The one site whose pages may send events. */
export const SITE_ORIGIN = "https://squadopt.mymandev.com";

/** Every answer carries this header, so a client can tell the Worker from the site's shell. */
export const MARKER_HEADER = "x-squadopt-usage";
export const MARKER_VALUE = "1";

/** The status answer's name, and the event version the Worker takes. */
export const STATUS_CONTRACT = "usage_status_v1";
export const EVENT_VERSION = 1;

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
  "reminder",
  "team",
  "fixtures",
  "contribute",
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
  "fixtures",
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

/**
 * The event a request carries, or a refusal naming the first thing wrong with it. Exactly the
 * seven fields, nothing beside them, so a page that started sending more would be refused
 * rather than quietly trimmed.
 */
export function eventFrom(body) {
  if (!isObject(body)) throw new RefusedError("body_not_object");
  if (Object.keys(body).sort().join() !== FIELDS.join()) throw new RefusedError("wrong_fields");
  if (body.v !== EVENT_VERSION) throw new RefusedError("wrong_version");
  if (typeof body.session !== "string" || !SESSION.test(body.session)) {
    throw new RefusedError("session_refused");
  }
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
 * The event as one Analytics Engine data point. The session is the index because the dataset
 * samples by index under heavy load, and a visit is only useful with its steps together.
 */
export function dataPoint(event) {
  return {
    indexes: [event.session],
    blobs: BLOB_COLUMNS.map((column) => event[column]),
    doubles: [event.v],
  };
}
