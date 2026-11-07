// The deadline reminder's rules, as plain functions with no I/O: what a subscription request
// must carry, which gameweek a run reminds of, what the notification says and where a tap on
// it opens. worker.js applies them; the tests hold them.
//
// See docs/architecture/decisions/0013-deadline-reminders.md.

/** The site the Worker sits in front of; its fixture list says when each deadline is. */
export const SITE_ORIGIN = "https://squadopt.mymandev.com";
export const SCHEDULE_URL = `${SITE_ORIGIN}/data/fixtures.json`;

/** Every answer carries this header, so a client can tell the Worker from the site's shell. */
export const MARKER_HEADER = "x-squadopt-push";
export const MARKER_VALUE = "1";

/** The request a page sends to be reminded, and the answer that names the key. */
export const SUBSCRIPTION_CONTRACT = "push_subscription_v1";
export const KEY_CONTRACT = "push_key_v1";

/** The reminder goes out inside this window before the deadline, once per gameweek. */
export const REMIND_BEFORE_MS = 3 * 60 * 60 * 1000;

/** A request body larger than this is refused before it is parsed. */
export const MAX_BODY_BYTES = 4096;

/** The hour the push service may hold an undelivered reminder; after it the deadline has passed. */
export const PUSH_TTL_SECONDS = 3 * 60 * 60;

export const LANGUAGES = new Set(["tr", "en"]);

export class RefusedError extends Error {
  constructor(reason) {
    super(reason);
    this.name = "RefusedError";
    this.reason = reason;
  }
}

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

/** base64url text, as the Push API encodes a subscription's keys. */
const BASE64URL = /^[A-Za-z0-9_-]+$/;

/**
 * The subscription a request carries, or a refusal naming the first thing wrong with it. The
 * endpoint must be an https address; the keys are the Push API's two base64url strings; the
 * language is one the site speaks; the league is 0 (a team on its own) or an FPL league id.
 */
export function subscriptionFrom(body) {
  if (!isObject(body)) throw new RefusedError("body_not_object");
  if (body.contract_version !== SUBSCRIPTION_CONTRACT) throw new RefusedError("wrong_contract");
  const endpoint = typeof body.endpoint === "string" ? body.endpoint : "";
  let url;
  try {
    url = new URL(endpoint);
  } catch {
    throw new RefusedError("endpoint_not_url");
  }
  if (url.protocol !== "https:" || endpoint.length > 2048) throw new RefusedError("endpoint_refused");
  const keys = isObject(body.keys) ? body.keys : null;
  if (keys === null) throw new RefusedError("keys_missing");
  for (const name of ["p256dh", "auth"]) {
    const value = keys[name];
    if (typeof value !== "string" || value.length < 16 || value.length > 256 || !BASE64URL.test(value)) {
      throw new RefusedError(`${name}_refused`);
    }
  }
  if (!LANGUAGES.has(body.language)) throw new RefusedError("language_refused");
  for (const name of ["league_id", "entry_id"]) {
    const value = body[name];
    if (!Number.isSafeInteger(value) || value < 0) throw new RefusedError(`${name}_refused`);
  }
  if (body.entry_id === 0) throw new RefusedError("entry_id_refused");
  return {
    endpoint,
    p256dh: keys.p256dh,
    auth: keys.auth,
    language: body.language,
    league_id: body.league_id,
    entry_id: body.entry_id,
  };
}

/** The endpoint a removal names, or a refusal. */
export function endpointFrom(body) {
  if (!isObject(body) || typeof body.endpoint !== "string") throw new RefusedError("endpoint_missing");
  try {
    if (new URL(body.endpoint).protocol !== "https:") throw new Error();
  } catch {
    throw new RefusedError("endpoint_refused");
  }
  return body.endpoint;
}

/**
 * The deadlines the site's fixture list states: `[{gameweek, deadlineMs}]`, sorted by time. A
 * document that is not a fixtures_v1 list, or a week without a readable deadline, is refused.
 */
export function deadlinesFrom(document) {
  if (!isObject(document) || document.contract_version !== "fixtures_v1") {
    throw new RefusedError("fixtures_not_v1");
  }
  const payload = isObject(document.payload) ? document.payload : null;
  if (payload === null || !Array.isArray(payload.gameweeks)) throw new RefusedError("fixtures_unreadable");
  const deadlines = payload.gameweeks.map((week) => {
    const gameweek = isObject(week) ? week.gameweek : null;
    const deadlineMs = isObject(week) ? Date.parse(week.deadline_utc) : NaN;
    if (!Number.isSafeInteger(gameweek) || gameweek < 1 || !Number.isFinite(deadlineMs)) {
      throw new RefusedError("fixtures_unreadable");
    }
    return { gameweek, deadlineMs };
  });
  return deadlines.sort((a, b) => a.deadlineMs - b.deadlineMs);
}

/**
 * The gameweek a run at `nowMs` reminds of: the one whose deadline is still ahead and within
 * the window. None when no deadline is that near, so a run between deadlines sends nothing.
 */
export function windowGameweek(deadlines, nowMs) {
  const due = deadlines.find(
    ({ deadlineMs }) => deadlineMs > nowMs && deadlineMs - nowMs <= REMIND_BEFORE_MS,
  );
  return due ?? null;
}

/** What the notification says, in the subscriber's language. */
export function message(gameweek, language) {
  return language === "tr"
    ? { title: `GW${gameweek}: son 3 saat`, body: "Planın hazır." }
    : { title: `GW${gameweek}: 3 hours left`, body: "Your plan is ready." };
}

/** Where a tap on the notification opens: the member's own page, or the team's on its own. */
export function targetPath(subscription) {
  return subscription.league_id > 0
    ? `/league/${subscription.league_id}/members/${subscription.entry_id}`
    : `/entry/${subscription.entry_id}`;
}

/** The notification's payload, as sw.js reads it. */
export function payloadFor(gameweek, subscription) {
  const words = message(gameweek, subscription.language);
  return { ...words, url: `${SITE_ORIGIN}${targetPath(subscription)}`, gameweek };
}

/** A push service answer that says the subscription is gone for good. */
export function subscriptionGone(status) {
  return status === 404 || status === 410;
}
