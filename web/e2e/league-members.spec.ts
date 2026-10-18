import { expect, test } from "@playwright/test";

import { installLeagueMocks } from "./leagueMocks";
import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";

test.beforeEach(async ({ page }) => {
  await installLeagueMocks(page);
});

for (const language of ["tr", "en"] as const) {
  test(`approved strategy names at 360 pixels (${language})`, async ({ page }, testInfo) => {
    const copy = MESSAGES[language].leagueMembers;
    await page.setViewportSize({ width: 360, height: 800 });
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    await page.goto("/league/352490/members/35249001");
    const settings = page.getByRole("region", { name: copy.planTitle });
    for (const strategy of Object.values(copy.strategies)) {
      await expect(
        settings.getByRole("radio", { name: new RegExp(`^${strategy.name}`) }),
      ).toBeVisible();
    }
    await expect(settings.getByRole("group", { name: copy.windowLegend })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
      false,
    );
    await settings.screenshot({ path: testInfo.outputPath(`approved-names-${language}-360.png`) });
  });
}

test("member list links to point-labelled advice and preserves its URL state", async ({ page }) => {
  await page.goto("/league/352490/members");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    mockLeagueMembersEnvelope.payload.league_name,
  );
  await expect(page.getByText("örnek veri")).toBeVisible();
  await expect(page.getByText("SquadOpt · sistem takımı")).toHaveCount(0);

  await page.getByRole("link", { name: "Deniz Aral" }).click();
  await expect(page).toHaveURL(/\/league\/352490\/members\/35249001$/);
  await expect(page.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toBeVisible();

  // Most points is published at three and five weeks; the page lists no assumptions.
  await expect(page.getByRole("radio", { name: /3 hafta/ })).toBeEnabled();
  await page.getByRole("radio", { name: /3 hafta/ }).click();
  await expect(page).toHaveURL(/window=3/);
  await expect(page.getByRole("region", { name: "3 haftalık pencere" })).toBeVisible();
  await expect(page.getByText(/Bu pencerenin varsaydıkları/)).toHaveCount(0);
  await page.getByRole("radio", { name: /1 hafta/ }).click();
  // A rival strategy stays at one week: the longer windows are shown disabled.
  await page.getByRole("radio", { name: /^Farkı koru/ }).click();
  await expect(page).toHaveURL(/mode=ortak-koru/);
  await expect(page.getByRole("radio", { name: /3 hafta/ })).toBeDisabled();
  const rival = page.getByRole("combobox", { name: "Karşısında oynadığın üye" });
  await expect(rival).toBeVisible();
  await rival.selectOption({ index: 1 });
  await expect(page).toHaveURL(/rival=\d+/);
  // The week's hit is a fact beside the gain; the sentences behind it are in the disclosure.
  await expect(page.getByText("0 ceza puanı")).toBeVisible();
  await page.locator("main details summary", { hasText: "Nasıl hesaplandı?" }).click();
  await expect(page.getByText(/beklenen puan maliyeti/).first()).toBeVisible();
  await expect(page.getByText(/Önerin senin kadrondan/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Kaydedilen puan farkı" })).toHaveCount(0);
  await expect(page.getByText(/rakibe karşı beklenen fark/)).toBeVisible();
  await expect(page.locator('[aria-labelledby="entry-advice-title"]')).not.toContainText("%");

  await page.reload();
  await expect(page.getByRole("radio", { name: /^Farkı koru/ })).toBeChecked();
  await expect(page).toHaveURL(/rival=\d+/);
});

test("member navigation is keyboard operable with reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/league/352490/members");

  const memberLink = page.getByRole("link", { name: "Deniz Aral" });
  await memberLink.focus();
  await expect(memberLink).toBeFocused();
  await expect(memberLink).toHaveCSS("outline-style", "solid");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/league\/352490\/members\/35249001$/);

  const mode = page.getByRole("radio", { name: /^Farkı kapat/ });
  await mode.focus();
  await page.keyboard.press("Space");
  await expect(mode).toBeChecked();

  const motion = await page.locator("main").evaluate((main) => {
    const probe = document.createElement("div");
    probe.style.animationDuration = "10s";
    probe.style.transitionDuration = "10s";
    main.append(probe);
    const style = getComputedStyle(probe);
    return { animation: style.animationDuration, transition: style.transitionDuration };
  });
  expect(motion).toEqual({ animation: "0s", transition: "0s" });
});
