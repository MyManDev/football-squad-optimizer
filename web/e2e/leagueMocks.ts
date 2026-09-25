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

/**
 * A calendar in which the mocked league's gameweek is still open. The member page reads
 * the published calendar to say when a deadline has passed and then stops offering
 * Compute; a spec that mocks a league must not change its outcome with the wall clock,
 * so the mocked week never closes. A spec about a closed week routes its own calendar
 * after calling `installLeagueMocks`.
 */
export function openCalendar() {
  const { season, gameweek } = mockLeagueMembersEnvelope.payload;
  return {
    contract_version: "fixtures_v1",
    generated_at_utc: mockLeagueMembersEnvelope.generated_at_utc,
    source_kind: mockLeagueMembersEnvelope.source_kind,
    payload: {
      season,
      source_snapshot_id: "fpl-live-mock",
      captured_at_utc: mockLeagueMembersEnvelope.generated_at_utc,
      current_gameweek: gameweek,
      unscheduled_count: 0,
      gameweeks: [{ gameweek, deadline_utc: "2999-01-01T00:00:00Z", fixtures: [] }],
    },
  };
}

/**
 * The published league, served from the fixtures, with the advice API refused.
 *
 * CI builds the site with the production API origin (`VITE_ADVICE_API_ORIGIN`), so a member
 * page asks that backend for its capabilities as soon as it opens. No spec may reach it:
 * every `/api/v1/` request is aborted as a refused connection, which the page reads as a
 * backend that is down. The abort is registered first, and Playwright tries the most
 * recently registered route first, so a spec that needs the API routes it after this call.
 */
export async function installLeagueMocks(page: Page) {
  await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
  await page.route("**/data/fixtures.json", (route) => fulfill(route, openCalendar()));
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
