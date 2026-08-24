import type { Page, Route } from "@playwright/test";

import { settledRecommendationFixture } from "../src/fixtures/settledRecommendation";

function fulfill(route: Route) {
  return route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      contract_version: "ui_view_v1",
      generated_at_utc: "2026-08-24T18:00:00Z",
      payload: settledRecommendationFixture,
    }),
  });
}

export async function installSettledRecommendationMock(page: Page) {
  await page.route("**/data/2026-27/gw01/recommendation.json", fulfill);
}
