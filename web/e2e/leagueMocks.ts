import type { Page, Route } from "@playwright/test";

import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../src/fixtures/league";
import type { PlayMode, WindowSize } from "../src/features/moves/modePrices";

const PLAY_MODES: readonly PlayMode[] = ["saf-puan", "garantici", "agresif", "asiri-agresif"];
const WINDOWS: readonly WindowSize[] = [1, 3, 5];

function isPlayMode(value: string | null): value is PlayMode {
  return PLAY_MODES.some((mode) => mode === value);
}

function fulfill(route: Route, value: unknown) {
  return route.fulfill({ contentType: "application/json", body: JSON.stringify(value) });
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
    return fixture
      ? fulfill(route, fixture)
      : route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
  await page.route(/\/data\/league\/advice\/(\d+)\/([^/]+)\/(\d+)\.json(?:\?.*)?$/, (route) => {
    const match = route
      .request()
      .url()
      .match(/advice\/(\d+)\/([^/]+)\/(\d+)\.json/);
    const entryId = Number(match?.[1]);
    const mode = match?.[2] ?? null;
    const window = Number(match?.[3]);
    if (!isPlayMode(mode) || !WINDOWS.includes(window as WindowSize)) {
      return route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    }
    return fulfill(route, mockEntryAdviceEnvelope(entryId, mode, window as WindowSize));
  });
}
