import { discardBody, withRequestDeadline, type RequestOptions } from "../../data/request";
import { LeagueDataError, LeagueDataMissing } from "./dataErrors";

/**
 * One published JSON document of the league trees, by its path under `data/`. A document
 * that is not published answers 404 (Pages' data/404.html) or, on a host without that
 * rule, the HTML application shell; both read as missing. A refused answer's body is read
 * and dropped, so the request ends.
 */
export async function fetchPublishedJson(
  base: string,
  relative: string,
  options?: RequestOptions,
): Promise<unknown> {
  return withRequestDeadline(async (signal) => {
    const response = await fetch(`${base}${relative}`, { cache: "no-cache", signal });
    if (!response.ok) {
      await discardBody(response);
      if (response.status === 404) throw new LeagueDataMissing(relative);
      throw new LeagueDataError(`League data is not available (${response.status}).`);
    }
    // A broken JSON publication is unreadable and must not become an example fallback.
    const body = await response.text();
    try {
      return JSON.parse(body) as unknown;
    } catch {
      if (/^\s*(?:<!doctype\s+html\b|<html\b)/i.test(body)) throw new LeagueDataMissing(relative);
      throw new LeagueDataError(`The published league document at ${relative} is not valid JSON.`);
    }
  }, options);
}

/**
 * One published file's bytes at a versioned address: the browser may keep it, because the
 * address changes whenever the bytes do. Missing reads as `LeagueDataMissing`.
 */
export async function fetchPublishedBytes(
  base: string,
  relative: string,
  options?: RequestOptions,
): Promise<ArrayBuffer> {
  return withRequestDeadline(async (signal) => {
    const response = await fetch(`${base}${relative}`, { signal });
    if (!response.ok) {
      await discardBody(response);
      if (response.status === 404) throw new LeagueDataMissing(relative);
      throw new LeagueDataError(`League data is not available (${response.status}).`);
    }
    return response.arrayBuffer();
  }, options);
}
