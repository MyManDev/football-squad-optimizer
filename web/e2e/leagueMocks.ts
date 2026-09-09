import type { Page, Route } from "@playwright/test";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../src/fixtures/league";
import type { AdviceStrategy } from "../src/features/league/types";
import type { WindowSize } from "../src/features/moves/modePrices";

const STRATEGIES: readonly AdviceStrategy[] = [
  "saf-puan",
  "ortak-koru",
  "fark-yarat",
  "garantici",
  "agresif",
  "asiri-agresif",
];
const WINDOWS: readonly WindowSize[] = [1, 3, 5];

function isStrategy(value: string | null): value is AdviceStrategy {
  return STRATEGIES.some((strategy) => strategy === value);
}

function fulfill(route: Route, value: unknown) {
  return route.fulfill({ contentType: "application/json", body: JSON.stringify(value) });
}

function missing(route: Route) {
  return route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
}

export async function installLeagueMocks(page: Page) {
  await page.route("**/data/league/members.json", (route) =>
    fulfill(route, mockLeagueMembersEnvelope),
  );
  await page.route(/\/data\/league\/entries\/(\d+)\.json(?:\?.*)?$/, (route) => {
    const match = route
      .request()
      .url()
      .match(/entries\/(\d+)\.json/);
    const fixture = match ? mockEntrySquadEnvelopes[Number(match[1])] : undefined;
    return fixture ? fulfill(route, fixture) : missing(route);
  });
  await page.route(/\/data\/league\/advice\/(\d+)\/index\.json(?:\?.*)?$/, (route) => {
    const match = route
      .request()
      .url()
      .match(/advice\/(\d+)\/index\.json/);
    return match ? fulfill(route, mockEntryAdviceIndex(Number(match[1]))) : missing(route);
  });
  // The producer's per-rival file: advice/{entry}/{strategy}/{window}/vs-{rival}.json.
  await page.route(
    /\/data\/league\/advice\/(\d+)\/([^/]+)\/(\d+)\/vs-(\d+)\.json(?:\?.*)?$/,
    (route) => {
      const match = route
        .request()
        .url()
        .match(/advice\/(\d+)\/([^/]+)\/(\d+)\/vs-(\d+)\.json/);
      const entryId = Number(match?.[1]);
      const mode = match?.[2] ?? null;
      const window = Number(match?.[3]);
      const rival = Number(match?.[4]);
      if (!isStrategy(mode) || !WINDOWS.includes(window as WindowSize)) return missing(route);
      return fulfill(route, mockEntryAdviceEnvelope(entryId, mode, window as WindowSize, rival));
    },
  );
  await page.route(/\/data\/league\/advice\/(\d+)\/([^/]+)\/(\d+)\.json(?:\?.*)?$/, (route) => {
    const match = route
      .request()
      .url()
      .match(/advice\/(\d+)\/([^/]+)\/(\d+)\.json/);
    const entryId = Number(match?.[1]);
    const mode = match?.[2] ?? null;
    const window = Number(match?.[3]);
    if (!isStrategy(mode) || !WINDOWS.includes(window as WindowSize)) return missing(route);
    return fulfill(route, mockEntryAdviceEnvelope(entryId, mode, window as WindowSize));
  });
}
