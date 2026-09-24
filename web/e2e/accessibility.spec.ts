import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { installLeagueMocks } from "./leagueMocks";
import { MESSAGES } from "../src/i18n/messages";

const ROUTES = [
  "/",
  "/gw/2026-27/1",
  "/moves",
  "/rivals",
  "/league",
  "/league/members",
  "/league/members/35249001?mode=saf-puan&window=3",
  "/league/members/squadopt",
  "/admin",
  "/status",
] as const;
const BLOCKING_IMPACTS = new Set(["critical", "serious"]);

async function waitForPage(page: import("@playwright/test").Page) {
  await expect(page.locator("main")).not.toContainText(/Yükleniyor|Loading/);
}

// The site has one palette (direction D is light only), so every route is checked in it,
// in both languages.
for (const language of ["tr", "en"] as const) {
  test(`axe has no critical or serious violations in ${language}`, async ({ page }) => {
    test.setTimeout(60_000);
    await installLeagueMocks(page);
    await page.addInitScript((selectedLanguage) => {
      localStorage.setItem("squadopt.language", selectedLanguage);
    }, language);

    for (const route of ROUTES) {
      await page.goto(route);
      await waitForPage(page);
      if (route.includes("mode=saf-puan&window=3")) {
        await expect(page.locator('[aria-labelledby="entry-advice-title"]')).toBeVisible();
        const plan = page.getByRole("region", {
          name: MESSAGES[language].leagueMembers.windowTitle(3),
        });
        await expect(plan).toBeVisible();
        await expect(plan.locator("tbody tr")).toHaveCount(3);
      }
      const results = await new AxeBuilder({ page }).analyze();
      const blocking = results.violations.filter((violation) =>
        BLOCKING_IMPACTS.has(violation.impact ?? ""),
      );
      const summary = blocking.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        nodes: violation.nodes.length,
        targets: violation.nodes.slice(0, 3).map((node) => node.target.join(" ")),
      }));
      expect(summary, `${language} ${route}`).toEqual([]);
    }
  });
}

test("language controls satisfy label-in-name and remain keyboard operable", async ({ page }) => {
  await page.goto("/");
  const turkish = page.getByRole("button", { name: /^TR/ });
  const english = page.getByRole("button", { name: /^EN/ });

  await expect(turkish).toHaveText("TR");
  await expect(english).toHaveText("EN");
  await english.focus();
  await page.keyboard.press("Enter");
  await expect(english).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
});

test("skip link and primary navigation expose visible keyboard focus", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");

  const skip = page.getByRole("link", { name: "İçeriğe geç" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await expect(skip).toHaveCSS("outline-style", "solid");

  await page.keyboard.press("Tab");
  const league = page.getByRole("link", { name: "Lig", exact: true });
  await expect(league).toBeFocused();
  await expect(league).toHaveCSS("outline-style", "solid");

  for (const name of ["Fikstür", "Katkıda bulun"]) {
    await page.keyboard.press("Tab");
    const link = page.getByRole("navigation").getByRole("link", { name, exact: true });
    await expect(link).toBeFocused();
    await expect(link).toHaveCSS("outline-style", "solid");
  }
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /^TR/ })).toBeFocused();
});
