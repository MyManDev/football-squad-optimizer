import { expect, test, type Browser, type Route } from "@playwright/test";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { atRest } from "./atRest";
import { installLeagueMocks } from "./leagueMocks";

// The model-switch highlight (#1131) in a real browser. The football model comes only from the
// compute service, so this runs on a build that names one (VITE_ADVICE_API_ORIGIN) and answers
// it here: the capabilities offer both models, and computing the football model's plan for the
// selection brings in two players. With motion the changed plates rise once; with the reduced-motion
// preference nothing moves; either way the page ends with the same marks and the same line.
const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const ENTRY = 35249001;
const COPY = MESSAGES.tr.leagueMembers;

function footballPlan() {
  const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
  const eleven = envelope.payload.starting_xi!;
  envelope.payload.starting_xi = eleven.map((player, index) =>
    index === 2 || index === 6
      ? { ...player, player_id: 900_000 + index, name: `Yeni ${index}`, short_name: `Yeni${index}` }
      : player,
  );
  envelope.payload.solver_status = "OPTIMAL";
  envelope.payload.expected_own_points = (envelope.payload.expected_own_points ?? 0) + 2.4;
  envelope.payload.prediction_model = {
    id: "football",
    version: "football_composite_v1",
    experimental: true,
    fingerprint: "e".repeat(64),
  };
  return envelope;
}

// The service is another origin, so its answers carry the CORS headers a real one sends, and
// the POST's preflight is answered.
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Idempotency-Key",
};

function answer(route: Route, status: number, json?: unknown) {
  if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
  return route.fulfill({ status, json, headers: CORS });
}

async function switchModel(browser: Browser, reducedMotion: "reduce" | "no-preference") {
  const page = await browser.newPage();
  await page.emulateMedia({ reducedMotion });
  await installLeagueMocks(page);
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  // Registered after the mocks, so these answer the service before their refusal does.
  await page.route(`${API}/api/v1/leagues/352490/capabilities**`, (route) =>
    answer(route, 200, {
      contract_version: "league_capabilities_v1",
      league_id: 352490,
      capture_snapshot_id: squad.source_snapshot_id,
      season: squad.season,
      gameweek: squad.gameweek,
      strategies: { "saf-puan": { windows: [1, 3, 5], requires_rival: false } },
      top100: { available: false, weights: [] },
      managers_word: { available: false },
      models: ["current", "football"],
    }),
  );
  // The service has nothing cached; asked to compute the football model, it answers at once.
  await page.route(`${API}/api/v1/leagues/352490/entries/${ENTRY}/advice**`, (route) =>
    route.request().method() === "POST" && route.request().url().includes("model=football")
      ? answer(route, 200, footballPlan())
      : answer(route, 404, { error: { code: "NOT_COMPUTED" } }),
  );
  await page.goto(`/league/352490/members/${ENTRY}?mode=saf-puan&window=1`);
  await expect(page.getByRole("heading", { name: COPY.decisionTitle })).toBeVisible();
  // The model is among the advanced settings, closed until asked for. The radio follows the
  // address, so the click is read back from it.
  await page.locator("main details summary", { hasText: COPY.advancedSettings }).click();
  await page.getByRole("radio", { name: COPY.modelNames.football }).click();
  await expect(page).toHaveURL(/model=football/);
  await page.getByRole("button", { name: "Hesapla", exact: true }).click();
  const line = page.locator("[data-model-change]");
  await expect(line).toBeVisible();
  await atRest(page);
  const state = {
    marked: await page
      .locator("[data-model-changed] [data-plate]")
      .evaluateAll((plates) => plates.map((plate) => plate.textContent)),
    line: await line.textContent(),
    url: page.url(),
  };
  await page.close();
  return state;
}

test("the model switch marks the same players and ends the same with and without motion", async ({
  browser,
}) => {
  test.skip(!API, "The build has no VITE_ADVICE_API_ORIGIN; the football model needs the service.");
  const moving = await switchModel(browser, "no-preference");
  const still = await switchModel(browser, "reduce");
  expect(moving.marked).toHaveLength(2);
  expect(moving.line).toContain(COPY.modelChangePlayers(COPY.modelNames.football, 2));
  expect(still).toEqual(moving);
});
