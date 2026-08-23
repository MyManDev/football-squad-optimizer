import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { settledRecommendationFixture } from "../src/fixtures/settledRecommendation";
import { installSettledRecommendationMock } from "./settledMocks";

test("the real settled contract fills the scorecard and player rows at 390px", async ({ page }) => {
  await installSettledRecommendationMock(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await expect(page.getByText("Projeksiyon ve gerçekleşen")).toBeVisible();
  await expect(page.getByText("×2 C", { exact: true })).toBeVisible();
  await expect(page.getByText(/^xP /).first()).toBeVisible();
  await expect(page.getByText(/^gerçekleşen /).first()).toBeVisible();
  await expect(page.getByText(/^fark /).first()).toBeVisible();
  await expect(
    page
      .getByText(String(settledRecommendationFixture.outcome_realized_score), { exact: true })
      .first(),
  ).toBeVisible();

  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);

  const results = await new AxeBuilder({ page }).analyze();
  const blocking = results.violations.filter((violation) =>
    new Set(["critical", "serious"]).has(violation.impact ?? ""),
  );
  expect(blocking).toEqual([]);
});
