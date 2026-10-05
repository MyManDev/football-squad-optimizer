/**
 * A `fetch` double that answers by address. A site publishes several documents at once
 * (the league directory, a league's members, a member's documents), and a test that
 * stubs one answer for every address cannot say which document it meant. Each route is
 * a suffix of the address, or a pattern; the first match answers, and an address no
 * route names is a 404, the way a static host answers an unpublished path.
 */

import { vi, type Mock } from "vitest";

export type FetchRoute = [match: string | RegExp, answer: (url: string) => Response];

export function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function notFound(): Response {
  return new Response("", { status: 404 });
}

function matches(url: string, match: string | RegExp): boolean {
  return typeof match === "string" ? url.endsWith(match) : match.test(url);
}

/** The double itself, so a test can assert which addresses were asked for. */
export function fetchByUrl(
  routes: FetchRoute[],
): Mock<(url: string, init?: RequestInit) => Promise<Response>> {
  return vi.fn(async (url: string) => {
    const route = routes.find(([match]) => matches(url, match));
    return route ? route[1](url) : notFound();
  });
}

/** Install the double as the global `fetch`; `vi.unstubAllGlobals()` removes it. */
export function stubFetchByUrl(routes: FetchRoute[]) {
  const fetcher = fetchByUrl(routes);
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
