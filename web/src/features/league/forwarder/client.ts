/**
 * The site's client of the FPL forwarder (ADR 0012, #983 step 3): one function per route, on
 * the site's own origin. An answer is taken only when it is the forwarder's: JSON, marked
 * `x-squadopt-fpl: 1`, and the document its contract names for what was asked. Anything else
 * is a typed refusal, never an exception, so a page that reads it falls back to the
 * published tree or shows nothing. A route the forwarder does not answer falls through to
 * the site's shell, which answers 200 with HTML; that is `not_forwarder`, not a document.
 */

import { discardBody, withRequestDeadline } from "../../../data/request";
import type { WeekLive } from "../../liveScore/weekLive";
import {
  LAST_GAMEWEEK,
  MAX_STANDINGS_PAGE,
  readEntryBundle,
  readLiveWeek,
  readStandings,
  type FplEntryBundle,
  type FplLeagueStandings,
} from "./documents";

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
 * - `network`: no answer, because the request failed or ran out of time;
 * - `aborted`: the caller stopped the read.
 */
export type ForwarderReason =
  | "not_found"
  | "head_to_head_league"
  | "league_not_found"
  | "page_not_found"
  | "entry_not_found"
  | "upstream_unavailable"
  | "not_forwarder"
  | "unreadable"
  | "network"
  | "aborted";

type LeagueRefusals = "head_to_head_league" | "league_not_found" | "page_not_found";
/** The reasons any route can give, whatever its own 404s are. */
type AnyRoute = "upstream_unavailable" | "not_forwarder" | "unreadable" | "network" | "aborted";
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
}

export interface ForwarderClientOptions {
  /** The transport; the browser's own unless a test injects one. */
  fetch?: (input: string, init: RequestInit) => Promise<Response>;
  /** Where the routes live; the site's own origin unless a test says otherwise. */
  root?: string;
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
}: ForwarderClientOptions = {}): ForwarderClient {
  /**
   * Ask one route, and read its answer as `read` reads a document, or as one of the
   * refusals `refusals` names for a 404. A 503 is always `upstream_unavailable`.
   */
  async function ask<T, R extends ForwarderReason>(
    path: string,
    read: (value: unknown) => T | null,
    refusals: readonly R[],
    { signal, timeoutMs }: ForwarderReadOptions = {},
  ): Promise<ForwarderResult<T, R | AnyRoute>> {
    try {
      return await withRequestDeadline(
        async (deadline) => {
          const response = await transport(`${root}${path}`, {
            signal: deadline,
            headers: { accept: "application/json" },
          });
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
    } catch {
      return { ok: false, reason: signal?.aborted ? "aborted" : "network" };
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
  };
}

/** The site's own client: the browser's fetch, on the site's origin. */
export const forwarder: ForwarderClient = createForwarderClient();

export const standings: ForwarderClient["standings"] = (league, page, options) =>
  forwarder.standings(league, page, options);
export const entryBundle: ForwarderClient["entryBundle"] = (entry, gameweek, options) =>
  forwarder.entryBundle(entry, gameweek, options);
export const liveWeek: ForwarderClient["liveWeek"] = (gameweek, options) =>
  forwarder.liveWeek(gameweek, options);
