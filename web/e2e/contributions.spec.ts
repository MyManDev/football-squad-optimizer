import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const language of ["tr", "en"] as const) {
  test(`mobile moderated contribution journey (${language})`, async ({ page }, testInfo) => {
    const tr = language === "tr";
    let posts = 0;
    await page.setViewportSize({ width: 375, height: 812 });
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    // External font availability is unrelated to the contribution contract.
    await page.route("https://fonts.googleapis.com/**", (route) => route.abort());
    await page.route("https://fonts.gstatic.com/**", (route) => route.abort());
    await page.route("**/api/v1/contributions**", async (route) => {
      const request = route.request();
      if (request.method() === "POST") {
        posts++;
        expect(request.postDataJSON()).toMatchObject({ player_id: 1, consent: true });
        return route.fulfill({ status: 202, json: { id: 42, status: "pending" } });
      }
      return route.fulfill({
        json: request.url().endsWith("/players")
          ? {
              season: "2026-27",
              captured_at_utc: "2026-09-22T12:00:00Z",
              teams: [{ id: 10, name: "Arsenal" }],
              players: [
                { id: 1, name: "Example Player", team_id: 10, team: "Arsenal", position: "GK" },
              ],
            }
          : { comments: [] },
      });
    });
    await page.goto("/contribute");
    await expect(
      page.getByRole("combobox", { name: tr ? "Pozisyon" : "Position", exact: true }),
    ).toBeDisabled();
    await page
      .getByRole("combobox", { name: tr ? "Takım" : "Team", exact: true })
      .selectOption("10");
    await page
      .getByRole("combobox", { name: tr ? "Pozisyon" : "Position", exact: true })
      .selectOption("GK");
    await page
      .getByRole("combobox", { name: tr ? "Oyuncu" : "Player", exact: true })
      .selectOption("1");
    await page.getByLabel(tr ? /Görünen ad/ : /Display name/).fill("Example fan");
    await page
      .getByLabel(tr ? "Oyuncu hakkında yorum" : "Player comment")
      .fill("The player occupied a deeper role in the second half.");
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: tr ? "Onaya gönder" : "Submit for approval" }).click();
    await expect(page.getByRole("status")).toContainText(
      tr ? "yönetici onayı bekliyor" : "awaits moderation",
    );
    expect(posts).toBe(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
      false,
    );
    const audit = await new AxeBuilder({ page }).analyze();
    expect(
      audit.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? "")),
    ).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath(`contribute-${language}.png`),
      fullPage: true,
    });
    await page.reload();
    await page
      .getByRole("combobox", { name: tr ? "Takım" : "Team", exact: true })
      .selectOption("10");
    await page
      .getByRole("combobox", { name: tr ? "Pozisyon" : "Position", exact: true })
      .selectOption("GK");
    await page
      .getByRole("combobox", { name: tr ? "Oyuncu" : "Player", exact: true })
      .selectOption("1");
    await expect(
      page.getByText(
        tr ? "Bu oyuncu için henüz onaylı yorum yok." : "No approved comments for this player yet.",
      ),
    ).toBeVisible();
  });
}
