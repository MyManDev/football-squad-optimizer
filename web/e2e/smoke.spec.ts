import { expect, test } from "@playwright/test";

import { claimMember, shippedClaim } from "./identity";

// The league pages stand behind the league number and "Sen kimsin?"; the visitor in this
// group has taken both, as the published league's first member.
test.describe("a visitor who has said who they are", () => {
  test.beforeEach(async ({ page }) => {
    await claimMember(page, shippedClaim());
  });

  test("league shows its title and the weekly scoreboard", async ({ page }) => {
    await page.goto("/league/352490");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lig Analizi");
    // This test runs against whatever is currently published, so every assertion in it has to
    // hold for any week of the season rather than for the week it was written in. The table
    // stands once a week has finished, and the card's own line stands before that.
    await expect(page.getByRole("heading", { name: "Haftalık skor tablosu" })).toBeVisible();
    await expect(
      page
        .getByRole("table", { name: /Biten her oyun haftası için/ })
        .or(page.getByText("Henüz biten oyun haftası yok.", { exact: true })),
    ).toBeVisible();
  });

  for (const address of [
    "/gw/2026-27/1",
    "/moves",
    "/status",
    "/admin",
    "/rivals",
    "/rivals/2026-27/1",
  ]) {
    test(`${address} falls to the not found state`, async ({ page }) => {
      await page.goto(address);
      await expect(page.getByRole("main").getByRole("status")).toHaveText("Burada bir sayfa yok.");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Burada bir sayfa yok.");
    });
  }

  test("language selection switches the full frame and persists across routes", async ({
    page,
  }) => {
    const member = shippedClaim();
    // CI builds with the production API origin; no spec may reach it (e2e/leagueMocks.ts).
    await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
    // The plan settings stand while the published week is open, so the clock stands before
    // every deadline of the season.
    await page.clock.setFixedTime(new Date("2026-08-01T00:00:00Z"));
    await page.goto(`/league/${member.leagueId}/members/${member.entryId}?mode=saf-puan&window=3`);
    await page.getByRole("button", { name: /EN.*English/ }).click();

    // The page's title is the member's team, so the words that change stand under it.
    await expect(page.getByRole("heading", { level: 2, name: "Plan Settings" })).toBeVisible();
    await expect(page.getByRole("radio", { name: /3 weeks/ })).toBeChecked();
    await expect(page).toHaveURL(/mode=saf-puan&window=3/);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");

    // 'League' is the member list, titled with the league's name; 'This Week' is the
    // visitor's own page.
    await page.getByRole("link", { name: "League", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(member.leagueName!);
    await page.reload();
    await expect(page.getByRole("link", { name: "League", exact: true })).toHaveAttribute(
      "href",
      `/league/${member.leagueId}/members`,
    );
    await expect(page.getByRole("link", { name: "This Week", exact: true })).toHaveAttribute(
      "href",
      `/league/${member.leagueId}/members/${member.entryId}`,
    );
  });
});

test("the sidebar's 'Find Your League' leads to the step without a member", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
  await page.goto("/fixtures");
  await page.getByRole("link", { name: "Find Your League", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Who are you?");
});
