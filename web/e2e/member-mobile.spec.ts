import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { MESSAGES } from "../src/i18n/messages";
import { mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { installLeagueMocks } from "./leagueMocks";

const apiOrigin = process.env.VITE_ADVICE_API_ORIGIN;

for (const language of ["tr", "en"] as const) {
  test(`member controls fit a phone in ${language}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await installLeagueMocks(page);
    await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.goto("/league/members/35249001?mode=saf-puan&window=3");
    const copy = MESSAGES[language];
    const details = page.locator("main details");
    await expect(details).toHaveCount(2);
    for (const detail of await details.all()) {
      await expect(detail).not.toHaveAttribute("open");
      await detail.locator("summary").click();
      await expect(detail).toHaveAttribute("open", "");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
      ).toBe(true);
      await detail.locator("summary").click();
    }
    const summary = page.getByTestId("member-selection-summary");
    await expect(summary).toContainText(copy.decision.week(3));
    await expect(summary).not.toContainText("Top 100 0");
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath(`member-top-${language}.png`) });
    await summary.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`member-summary-${language}.png`) });
    const tableScroll = page.locator('div[tabindex="0"]').filter({ has: page.locator("table") });
    await tableScroll.focus();
    await page.keyboard.press("ArrowRight");
    await expect
      .poll(() => tableScroll.evaluate((element) => element.scrollLeft))
      .toBeGreaterThan(0);
    const controls = page.getByRole("radio", { name: /^1 / });
    await controls.scrollIntoViewIfNeeded();
    await expect(
      page.getByRole("button", { name: copy.leagueMembers.computeButton, exact: true }),
    ).toBeInViewport();
    await expect
      .poll(async () => {
        const box = await page.locator("[data-compute-dock]").boundingBox();
        return box ? Math.abs(box.y + box.height - 812) : 999;
      })
      .toBeLessThanOrEqual(1);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    const results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? "")),
    ).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath(`member-mobile-${language}.png`),
      fullPage: true,
    });
    await page.screenshot({ path: testInfo.outputPath(`member-controls-${language}.png`) });
    await page.setViewportSize({ width: 1280, height: 900 });
    for (const detail of await details.all()) await expect(detail).toHaveAttribute("open", "");
    await page.setViewportSize({ width: 375, height: 812 });
    await expect
      .poll(() =>
        page.evaluate(() => getComputedStyle(document.documentElement).scrollPaddingBottom),
      )
      .not.toBe("auto");
    await page.getByRole("link", { name: copy.leagueMembers.backToMembers, exact: true }).click();
    await expect
      .poll(() =>
        page.evaluate(() => getComputedStyle(document.documentElement).scrollPaddingBottom),
      )
      .toBe("auto");
  });

  test(`waiting compute dock stays compact in ${language}`, async ({ page }, testInfo) => {
    test.skip(
      !apiOrigin,
      "The build has no VITE_ADVICE_API_ORIGIN; a static build cannot enter a compute job.",
    );
    await page.setViewportSize({ width: 375, height: 667 });
    await installLeagueMocks(page);
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    const squad = mockEntrySquadEnvelopes[35249001]!.payload;
    await page.route("**/api/v1/**", async (route) => {
      const headers = {
        "access-control-allow-origin": new URL(page.url()).origin,
        "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-allow-headers": "content-type, idempotency-key",
      };
      if (route.request().method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers });
        return;
      }
      const url = route.request().url();
      const [status, body] = url.endsWith("/capabilities")
        ? [
            200,
            {
              contract_version: "league_capabilities_v1",
              league_id: squad.league_id,
              season: squad.season,
              gameweek: squad.gameweek,
              capture_snapshot_id: squad.source_snapshot_id,
              strategies: { "saf-puan": { windows: [1, 3, 5], requires_rival: false } },
              top100: { available: true, weights: [0, 20] },
              managers_word: { available: false },
            },
          ]
        : url.includes("/advice-jobs/")
          ? [200, { job_id: "mobile-waiting", status: "running" }]
          : route.request().method() === "POST"
            ? [202, { job_id: "mobile-waiting" }]
            : [404, { error: { code: "NOT_COMPUTED" } }];
      await route.fulfill({
        status: status as number,
        contentType: "application/json",
        headers,
        body: JSON.stringify(body),
      });
    });
    await page.goto("/league/members/35249001?window=3&top100=20");
    const copy = MESSAGES[language].leagueMembers;
    await page.getByRole("button", { name: copy.computeButton, exact: true }).click();
    await expect(page.getByText(copy.computeRunning, { exact: true })).toBeVisible();
    await page.getByRole("radio", { name: /^1 / }).scrollIntoViewIfNeeded();
    const dock = page.locator("[data-compute-dock]");
    const box = await dock.boundingBox();
    expect(box!.height).toBeLessThanOrEqual(667 * 0.45 + 1);
    expect(Math.abs(box!.y + box!.height - 667)).toBeLessThanOrEqual(1);
    const badge = await dock.getByText(copy.computeRunning, { exact: true }).boundingBox();
    const state = await dock
      .getByText(copy.computeWaitingWithFallback, { exact: false })
      .boundingBox();
    for (const visible of [badge, state]) {
      expect(visible).not.toBeNull();
      expect(visible!.y).toBeGreaterThanOrEqual(box!.y);
      expect(visible!.y + visible!.height).toBeLessThanOrEqual(box!.y + box!.height);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`member-waiting-${language}.png`) });
  });
}
