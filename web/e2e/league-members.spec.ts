import { expect, test } from "@playwright/test";

import { installLeagueMocks } from "./leagueMocks";

test.beforeEach(async ({ page }) => {
  await installLeagueMocks(page);
});

test("member list links to point-labelled advice and preserves its URL state", async ({ page }) => {
  await page.goto("/league/members");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lig üyeleri");
  await expect(page.getByText("örnek veri")).toBeVisible();
  await expect(page.getByText("SquadOpt · sistem takımı")).toBeVisible();

  await page.getByRole("link", { name: "Deniz Aral" }).click();
  await expect(page).toHaveURL(/\/league\/members\/35249001$/);
  await expect(page.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toBeVisible();

  await page.getByRole("radio", { name: /3 hafta/ }).click();
  await page.getByRole("radio", { name: /^Agresif/ }).click();
  await expect(page).toHaveURL(/mode=agresif/);
  await expect(page).toHaveURL(/window=3/);
  await expect(page.getByText(/beklenen puan maliyeti/).first()).toBeVisible();
  await expect(page.getByText(/yalnızca senin kadrondan/)).toBeVisible();
  await expect(page.getByText(/puan farkın: \+9/)).toBeVisible();
  await expect(page.locator('[aria-labelledby="entry-advice-title"]')).not.toContainText("%");

  await page.reload();
  await expect(page.getByRole("radio", { name: /^Agresif/ })).toBeChecked();
  await expect(page.getByRole("radio", { name: /3 hafta/ })).toBeChecked();
});

test("the virtual SquadOpt member reuses the existing squad view without probability claims", async ({
  page,
}) => {
  await page.goto("/league/members");
  await page.getByRole("link", { name: "SquadOpt", exact: true }).click();

  await expect(page).toHaveURL(/\/league\/members\/squadopt$/);
  await expect(page.getByText("SquadOpt da oynuyor")).toBeVisible();
  await expect(page.getByText(/Sistemin kendi takımı bu hesaba girmez/)).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Oyun haftası 1/);
  await expect(page.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toBeVisible();
  await expect(page.getByText("SquadOpt da oynuyor").locator("..")).not.toContainText("%");
});

test("member navigation is keyboard operable with reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/league/members");

  const memberLink = page.getByRole("link", { name: "Deniz Aral" });
  await memberLink.focus();
  await expect(memberLink).toBeFocused();
  await expect(memberLink).toHaveCSS("outline-style", "solid");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/league\/members\/35249001$/);

  const mode = page.getByRole("radio", { name: /^Garantici/ });
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
