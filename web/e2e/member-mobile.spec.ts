import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";

for (const language of ["tr", "en"] as const) {
  test(`member controls fit a phone in ${language}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await installLeagueMocks(page);
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.goto("/league/members/35249001?mode=saf-puan&window=3");
    const copy = MESSAGES[language];
    const details = page.locator("main details");
    await expect(details).toHaveCount(2);
    for (const detail of await details.all()) {
      await expect(detail).not.toHaveAttribute("open");
      await detail.locator("summary").click();
      await expect(detail).toHaveAttribute("open", "");
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(375);
      await detail.locator("summary").click();
    }
    const summary = page.getByTestId("member-selection-summary");
    await expect(summary).toContainText(copy.decision.week(3));
    await expect(summary).toContainText("Top 100 0");
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
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(375);
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
  });
}
