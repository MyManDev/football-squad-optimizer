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

/** The ids of axe's critical and serious findings on the page as it stands. */
async function blockingViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations
    .filter((violation) => BLOCKING_IMPACTS.has(violation.impact ?? ""))
    .map((violation) => violation.id);
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

test("language buttons are 44 px touch targets below 1180 px wide", async ({ page }) => {
  // Desktop keeps D's compact 30 px control; every narrower width is treated as touch.
  // On a phone the switch lives in the sidebar drawer, so the menu is opened first; the
  // tablet's icon rail stacks TR over EN.
  for (const [width, minHeight, minWidth] of [
    [390, 44, 44],
    [1179, 44, 44],
    [1440, 28, 40],
  ] as const) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    if (width < 600) {
      await page.getByRole("button", { name: "Menüyü aç" }).click();
      // Measure once the drawer has finished sliding in, not part way through it.
      await expect(page.locator("#sidebar")).toHaveCSS("transform", "none");
    }
    for (const name of [/^TR/, /^EN/]) {
      const box = await page.getByRole("button", { name }).boundingBox();
      expect(box, `${String(name)} at ${width}`).not.toBeNull();
      expect(box!.height, `${String(name)} height at ${width}`).toBeGreaterThanOrEqual(minHeight);
      expect(box!.width, `${String(name)} width at ${width}`).toBeGreaterThanOrEqual(minWidth);
    }
  }
});

test("skip link and the sidebar's controls take keyboard focus in order", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.keyboard.press("Tab");

  const skip = page.getByRole("link", { name: "İçeriğe geç" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await expect(skip).toHaveCSS("outline-style", "solid");

  // Then the sidebar, in the order it stands: its collapse button, the navigation, the
  // language switch and the operations link.
  const sidebar = page.locator("#sidebar");
  const navigation = page.getByRole("navigation");
  const order = [
    sidebar.getByRole("button", { name: "Kenar çubuğunu kapat" }),
    navigation.getByRole("link", { name: "Bu hafta", exact: true }),
    navigation.getByRole("link", { name: "Lig", exact: true }),
    navigation.getByRole("link", { name: "Fikstür", exact: true }),
    navigation.getByRole("link", { name: "Katkıda bulun", exact: true }),
    sidebar.getByRole("button", { name: /^TR/ }),
    sidebar.getByRole("button", { name: /^EN/ }),
    sidebar.getByRole("link", { name: "Operasyon Durumu" }),
  ];
  for (const control of order) {
    await page.keyboard.press("Tab");
    await expect(control).toBeFocused();
    await expect(control).toHaveCSS("outline-style", "solid");
  }
  await expect(navigation.getByRole("link", { name: "Bu hafta", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("the phone menu is a modal drawer that keeps focus and gives it back", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installLeagueMocks(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ligini bul");
  // The sidebar is off the screen until the menu opens.
  await expect(page.getByRole("navigation")).toBeHidden();

  const menu = page.getByRole("banner").getByRole("button", { name: "Menüyü aç" });
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  await menu.click();
  const drawer = page.getByRole("dialog", { name: "Menü" });
  await expect(drawer).toBeVisible();
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  const close = drawer.getByRole("button", { name: "Menüyü kapat" });
  await expect(close).toBeFocused();
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).toBe(
    "hidden",
  );

  // Tab never leaves the drawer for the page behind it.
  for (let step = 0; step < 12; step += 1) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(() => {
      const active = document.activeElement;
      return active === document.body || !!active?.closest("#sidebar");
    });
    expect(inside, `focus after ${step + 1} tabs`).toBe(true);
  }

  expect(await blockingViolations(page)).toEqual([]);

  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(menu).toBeFocused();
  await expect(page.getByRole("navigation")).toBeHidden();
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).not.toBe(
    "hidden",
  );
});

test("the tablet rail names every icon and opens the sidebar over the page", async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 1180 });
  await page.goto("/");
  const navigation = page.getByRole("navigation");
  for (const name of ["Bu hafta", "Lig", "Fikstür", "Katkıda bulun"]) {
    const link = navigation.getByRole("link", { name, exact: true });
    await expect(link).toBeVisible();
    const box = (await link.boundingBox())!;
    expect(box.width, name).toBeGreaterThanOrEqual(44);
    expect(box.height, name).toBeGreaterThanOrEqual(44);
  }
  const rail = (await page.locator("#sidebar").boundingBox())!;
  expect(rail.width).toBe(72);

  const expand = page.getByRole("button", { name: "Kenar çubuğunu aç" });
  // The rail's other controls are touch targets too.
  for (const control of [expand, page.getByRole("link", { name: "Operasyon Durumu" })]) {
    const box = (await control.boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
  }
  expect(await blockingViolations(page)).toEqual([]);

  await expand.click();
  const drawer = page.getByRole("dialog", { name: "Menü" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("button", { name: "Menüyü kapat" })).toBeFocused();
  // The page column does not move under the drawer.
  expect((await page.getByRole("main").boundingBox())!.x).toBeGreaterThanOrEqual(72);
  expect(await blockingViolations(page)).toEqual([]);
  await page.locator("[class*=scrim]").click({ position: { x: 700, y: 400 } });
  await expect(drawer).toHaveCount(0);
});

test("the desktop sidebar collapses to the rail and stays so after a reload", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const sidebar = page.locator("#sidebar");
  expect((await sidebar.boundingBox())!.width).toBe(264);

  await page.getByRole("button", { name: "Kenar çubuğunu kapat" }).click();
  await expect(page.getByRole("button", { name: "Kenar çubuğunu aç" })).toBeFocused();
  expect((await sidebar.boundingBox())!.width).toBe(72);
  await page.reload();
  await expect(page.getByRole("button", { name: "Kenar çubuğunu aç" })).toBeVisible();
  expect((await sidebar.boundingBox())!.width).toBe(72);
  expect((await page.getByRole("main").boundingBox())!.x).toBeGreaterThanOrEqual(72);
  // The rail keeps every destination by name.
  await expect(
    page.getByRole("navigation").getByRole("link", { name: "Lig", exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("squadopt.sidebar"))).toBe("collapsed");
  expect(await blockingViolations(page)).toEqual([]);
});
