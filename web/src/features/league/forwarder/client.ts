/**
 * The site's client of the FPL forwarder (ADR 0012, #983 step 3): one function per route, on
 * the site's own origin. An answer is taken only when it is the forwarder's: JSON, marked
 * `x-squadopt-fpl: 1`, and the document its contract names for what was asked. Anything else
 * is a typed refusal, never an exception, so a page that reads it falls back to the
 * published tree or shows nothing. A route the forwarder does not answer falls through to
 * the site's shell, which answers 200 with HTML; that is `not_forwarder`, not a document.
 */

import { discardBody, withRequestDeadline } from "../../../data/request";
import type { WeekActivity } from "../../liveScore/weekActivity";
import type { WeekLive } from "../../liveScore/weekLive";
import {
  LAST_GAMEWEEK,
  MAX_STANDINGS_PAGE,
  readEntryBundle,
  readEntrySeason,
  readEvents,
  readH2hMatches,
  readH2hStandings,
  readLiveActivity,
  readLiveWeek,
  readStandings,
  type FplEntryBundle,
  type FplLeagueStandings,
  type FplEntrySeason,
  type FplEvents,
  type FplH2hMatches,
  type FplH2hStandings,
} from "./documents";
import { createRequestBudget, type RequestBudget, type RequestLane } from "./requestBudget";

/** The forwarder's routes, on the site's own origin. */
export const FORWARDER_ROOT = "/api/v1/fpl";
/** Every answer of the forwarder carries this header, refusals included. */
export const MARKER_HEADER = "x-squadopt-fpl";
/** Whether a document was read just now, is a data centre's copy, or the last good one. */
export const COPY_HEADER = "x-squadopt-fpl-cache";

/**
 * Whether a same-origin answer is one of the forwarder's own refusals that a page reads as
 * "no document": a 404 or a 503 on a path under its routes, carrying its mark. A release
 * check that counts failed answers leaves exactly these out, and counts every other one,
 * an unmarked 404 or a marked 500 included. `marker` is the answer's `x-squadopt-fpl`.
 */
export function isForwarderRefusal(
  pathname: string,
  status: number,
  marker: string | null | undefined,
): boolean {
  return (
    pathname.startsWith(`${FORWARDER_ROOT}/`) &&
    marker === "1" &&
    (status === 404 || status === 503)
  );
}

/**
 * Why a read gave no document:
 *
 * - `not_found`: the forwarder's 404 for an id, page or gameweek it does not serve now;
 * - `head_to_head_league`, `league_not_found`, `page_not_found`, `entry_not_found`: its 404s
 *   for what FPL does not have as asked;
 * - `upstream_unavailable`: its 503, when FPL failed and it holds no last good copy;
 * - `not_forwarder`: an answer without the forwarder's mark, such as the site's HTML shell;
 * - `unreadable`: the forwarder's mark on an answer this client does not read: not JSON,
 *   another `contract_version`, another shape or identity, or a status or error it does not name;
 * - `rate_limited`: the zone's rate rule still refused the read after waiting out its block;
 * - `network`: no answer, because the request failed or ran out of time;
 * - `aborted`: the caller stopped the read.
 */
export type ForwarderReason =
  | "not_found"
  | "head_to_head_league"
  | "classic_league"
  | "league_not_found"
  | "page_not_found"
  | "entry_not_found"
  | "upstream_unavailable"
  | "not_forwarder"
  | "unreadable"
  | "rate_limited"
  | "network"
  | "aborted";

type LeagueRefusals =
  "head_to_head_league" | "classic_league" | "league_not_found" | "page_not_found";
/** The reasons any route can give, whatever its own 404s are. */
type AnyRoute =
  "upstream_unavailable" | "not_forwarder" | "unreadable" | "rate_limited" | "network" | "aborted";
export type StandingsReason = Exclude<ForwarderReason, "entry_not_found">;
export type BundleReason = Exclude<ForwarderReason, LeagueRefusals>;
export type LiveReason = Exclude<ForwarderReason, LeagueRefusals | "entry_not_found">;

/** The `x-squadopt-fpl-cache` header's word, or null when the answer carries none. */
export type ForwarderCopy = "miss" | "hit" | "last-good";

export type ForwarderResult<T, R extends ForwarderReason = ForwarderReason> =
  { ok: true; document: T; copy: ForwarderCopy | null } | { ok: false; reason: R };

export interface ForwarderReadOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface ForwarderClient {
  /** One page of a classic league, 1 to 20. */
  standings(
    league: number,
    page: number,
    options?: ForwarderReadOptions,
  ): Promise<ForwarderResult<FplLeagueStandings, StandingsReason>>;
  /** One entry's bundle for a table gameweek, 2 to 38. */
  entryBundle(
    entry: number,
    gameweek: number,
    options?: ForwarderReadOptions,
  ): Promise<ForwarderResult<FplEntryBundle, BundleReason>>;
  /** One week's live points, 1 to 38. */
  liveWeek(
    gameweek: number,
    options?: ForwarderReadOptions,
  ): Promise<ForwarderResult<WeekLive, LiveReason>>;
  /** Opt-in event detail; older clients and the original live route remain valid. */
  liveActivity?(
    gameweek: number,
    options?: ForwarderReadOptions,
  ): Promise<ForwarderResult<WeekActivity, LiveReason>>;
  /** One entry's season to date: each played week's points, totals, ranks and transfers. */
  entrySeason(
    entry: number,
    options?: ForwarderReadOptions,
  ): Promise<ForwarderResult<FplEntrySeason, BundleReason>>;
  /** The season's gameweeks with the game's average and highest score. */
  events(options?: ForwarderReadOptions): Promise<ForwarderResult<FplEvents, LiveReason>>;
  /** One page of a head-to-head league's table, 1 to 1000. */
  h2hStandings(
    league: number,
    page: number,
    options?: ForwarderReadOptions,
  ): Promise<ForwarderResult<FplH2hStandings, StandingsReason>>;
  /** One page of a head-to-head league's pairings for one gameweek. */
  h2hMatches(
    league: number,
    gameweek: number,
    page: number,
    options?: ForwarderReadOptions,
  ): Promise<ForwarderResult<FplH2hMatches, StandingsReason>>;
}

export interface ForwarderClientOptions {
  /** The transport; the browser's own unless a test injects one. */
  fetch?: (input: string, init: RequestInit) => Promise<Response>;
  /** Where the routes live; the site's own origin unless a test says otherwise. */
  root?: string;
  /**
   * How many reads may start in the rate rule's window; one per client, so every read the
   * site makes through its one client shares it (`requestBudget.ts`).
   */
  budget?: RequestBudget;
  /** Waits out a rate block; the page's own timer unless a test injects one. */
  wait?: (durationMs: number, signal?: AbortSignal) => Promise<void>;
}

/**
 * How long a refused read waits before it is sent again: the answer's `Retry-After` in
 * seconds, else the rule's block of 10 seconds, never more than 30.
 */
export function rateBlockMs(retryAfter: string | null): number {
  const seconds = retryAfter !== null && /^\d+$/.test(retryAfter.trim()) ? Number(retryAfter) : 10;
  return Math.min(Math.max(seconds, 1), 30) * 1000;
}

/** How many times a read the rate rule refused is sent again before it says so. */
export const RATE_RETRIES = 2;

function pause(durationMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("The read was stopped.", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", stop);
      resolve();
    }, durationMs);
    function stop() {
      clearTimeout(timer);
      reject(new DOMException("The read was stopped.", "AbortError"));
    }
    signal?.addEventListener("abort", stop, { once: true });
  });
}

const COPIES: readonly string[] = ["miss", "hit", "last-good"];

function positiveId(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 1;
}

function inRange(value: number, first: number, last: number): boolean {
  return Number.isSafeInteger(value) && value >= first && value <= last;
}

export function createForwarderClient({
  fetch: transport = (input, init) => globalThis.fetch(input, init),
  root = FORWARDER_ROOT,
  budget = createRequestBudget(),
  wait = pause,
}: ForwarderClientOptions = {}): ForwarderClient {
  /**
   * Ask one route, and read its answer as `read` reads a document, or as one of the
   * refusals `refusals` names for a 404. A 503 is always `upstream_unavailable`. The read
   * waits for its lane's turn in the budget first, and its deadline starts when it is sent.
   * A 429 is the zone's rate rule, not the forwarder: the read waits out the block (and holds
   * the budget, so the reads behind it wait too) and is sent again, up to `RATE_RETRIES`.
   */
  async function ask<T, R extends ForwarderReason>(
    path: string,
    read: (value: unknown) => T | null,
    refusals: readonly R[],
    { signal, timeoutMs }: ForwarderReadOptions = {},
    lane: RequestLane = "page",
  ): Promise<ForwarderResult<T, R | AnyRoute>> {
    try {
      for (let attempt = 0; ; attempt += 1) {
        const turn = budget.take(lane, signal);
        if (turn !== null) await turn;
        const answer = await send();
        if (!("blockMs" in answer)) return answer;
        if (attempt >= RATE_RETRIES) return { ok: false, reason: "rate_limited" };
        budget.hold?.(answer.blockMs);
        await wait(answer.blockMs, signal);
      }
    } catch {
      return { ok: false, reason: signal?.aborted ? "aborted" : "network" };
    }

    function send(): Promise<ForwarderResult<T, R | AnyRoute> | { blockMs: number }> {
      return withRequestDeadline(
        async (deadline) => {
          const response = await transport(`${root}${path}`, {
            signal: deadline,
            headers: { accept: "application/json" },
          });
          if (response.status === 429) {
            await discardBody(response);
            return { blockMs: rateBlockMs(response.headers.get("retry-after")) };
          }
          if (response.headers.get(MARKER_HEADER) !== "1") {
            await discardBody(response);
            return { ok: false, reason: "not_forwarder" } as const;
          }
          const type = response.headers.get("content-type") ?? "";
          if (!/^application\/json\b/i.test(type)) {
            await discardBody(response);
            return { ok: false, reason: "unreadable" } as const;
          }
          const text = await response.text();
          let body: unknown;
          try {
            body = JSON.parse(text);
          } catch {
            return { ok: false, reason: "unreadable" } as const;
          }
          if (response.status === 200) {
            const document = read(body);
            if (document === null) return { ok: false, reason: "unreadable" } as const;
            const copy = response.headers.get(COPY_HEADER);
            return {
              ok: true,
              document,
              copy: copy !== null && COPIES.includes(copy) ? (copy as ForwarderCopy) : null,
            } as const;
          }
          const kind =
            typeof body === "object" && body !== null && !Array.isArray(body)
              ? (body as { error?: unknown }).error
              : undefined;
          if (response.status === 503 && kind === "upstream_unavailable") {
            return { ok: false, reason: "upstream_unavailable" } as const;
          }
          const refusal = refusals.find((name) => name === kind);
          if (response.status === 404 && refusal !== undefined) {
            return { ok: false, reason: refusal } as const;
          }
          return { ok: false, reason: "unreadable" } as const;
        },
        { signal, timeoutMs },
      );
    }
  }

  return {
    async standings(league, page, options) {
      if (!positiveId(league) || !inRange(page, 1, MAX_STANDINGS_PAGE)) {
        return { ok: false, reason: "not_found" };
      }
      return ask(
        `/standings/${league}?page=${page}`,
        (value) => readStandings(value, league, page),
        ["not_found", "head_to_head_league", "league_not_found", "page_not_found"] as const,
        options,
      );
    },
    async entryBundle(entry, gameweek, options) {
      if (!positiveId(entry) || !inRange(gameweek, 2, LAST_GAMEWEEK)) {
        return { ok: false, reason: "not_found" };
      }
      return ask(
        `/entry/${entry}/bundle?gw=${gameweek}`,
        (value) => readEntryBundle(value, entry, gameweek),
        ["not_found", "entry_not_found"] as const,
        options,
      );
    },
    async liveWeek(gameweek, options) {
      if (!inRange(gameweek, 1, LAST_GAMEWEEK)) return { ok: false, reason: "not_found" };
      return ask(
        `/live/${gameweek}`,
        (value) => readLiveWeek(value, gameweek),
        ["not_found"] as const,
        options,
      );
    },
    async liveActivity(gameweek, options) {
      if (!inRange(gameweek, 1, LAST_GAMEWEEK)) return { ok: false, reason: "not_found" };
      return ask(
        `/live/${gameweek}?view=activity`,
        (value) => readLiveActivity(value, gameweek),
        ["not_found"] as const,
        options,
      );
    },
    async entrySeason(entry, options) {
      if (!positiveId(entry)) return { ok: false, reason: "not_found" };
      return ask(
        `/entry/${entry}/season`,
        (value) => readEntrySeason(value, entry),
        ["not_found", "entry_not_found"] as const,
        options,
        // A scoreboard reads one season per member at once: the reads that can wait.
        "bulk",
      );
    },
    async events(options) {
      return ask("/events", readEvents, ["not_found"] as const, options);
    },
    async h2hStandings(league, page, options) {
      if (!positiveId(league) || !inRange(page, 1, MAX_STANDINGS_PAGE)) {
        return { ok: false, reason: "not_found" };
      }
      return ask(
        `/h2h/${league}/standings?page=${page}`,
        (value) => readH2hStandings(value, league, page),
        ["not_found", "classic_league", "league_not_found", "page_not_found"] as const,
        options,
      );
    },
    async h2hMatches(league, gameweek, page, options) {
      if (
        !positiveId(league) ||
        !inRange(gameweek, 1, LAST_GAMEWEEK) ||
        !inRange(page, 1, MAX_STANDINGS_PAGE)
      ) {
        return { ok: false, reason: "not_found" };
      }
      return ask(
        `/h2h/${league}/matches?gw=${gameweek}&page=${page}`,
        (value) => readH2hMatches(value, league, gameweek, page),
        ["not_found", "league_not_found", "page_not_found"] as const,
        options,
      );
    },
  };
}

/** The share of the rate rule the site's client spends, one per tab. */
let siteBudget: RequestBudget = createRequestBudget();

/**
 * Start the site's client on a fresh share. Tests do this between cases, as they clear the
 * session's storage, so one case's reads do not spend the next one's window.
 */
export function resetSiteForwarderBudget(): void {
  siteBudget = createRequestBudget();
}

/** The site's own client: the browser's fetch, on the site's origin. */
export const forwarder: ForwarderClient = createForwarderClient({
  budget: {
    take: (lane, signal) => siteBudget.take(lane, signal),
    hold: (durationMs) => siteBudget.hold?.(durationMs),
  },
});

export const standings: ForwarderClient["standings"] = (league, page, options) =>
  forwarder.standings(league, page, options);
export const entryBundle: ForwarderClient["entryBundle"] = (entry, gameweek, options) =>
  forwarder.entryBundle(entry, gameweek, options);
export const liveWeek: ForwarderClient["liveWeek"] = (gameweek, options) =>
  forwarder.liveWeek(gameweek, options);
export const entrySeason: ForwarderClient["entrySeason"] = (entry, options) =>
  forwarder.entrySeason(entry, options);
export const events: ForwarderClient["events"] = (options) => forwarder.events(options);
export const h2hStandings: ForwarderClient["h2hStandings"] = (league, page, options) =>
  forwarder.h2hStandings(league, page, options);
export const h2hMatches: ForwarderClient["h2hMatches"] = (league, gameweek, page, options) =>
  forwarder.h2hMatches(league, gameweek, page, options);
