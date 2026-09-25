import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { installLeagueMocks } from "./leagueMocks";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";

for (const language of ["tr", "en"] as const) {
  test(`human chooses and revisits plans on mobile (${language})`, async ({ page }, testInfo) => {
    const tr = language === "tr";
    await page.setViewportSize({ width: 375, height: 812 });
    await installLeagueMocks(page);
    // Legacy fixtures omit the squad-basis claim. This comparison explicitly proves it.
    await page.route(
      /\/data\/league\/advice\/35249001\/saf-puan\/[35]\.json(?:\?.*)?$/,
      (route) => {
        const window = route.request().url().includes("/5.json") ? 5 : 3;
        const envelope = mockEntryAdviceEnvelope(35249001, "saf-puan", window);
        envelope.payload.squad_basis = mockEntrySquadEnvelopes[35249001]!.payload.squad_basis;
        return route.fulfill({ contentType: "application/json", body: JSON.stringify(envelope) });
      },
    );
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    const posts: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST") posts.push(r.url());
    });
    await page.goto("/league/members/35249001?window=3");
    // The decision board is one of the page's tools, closed until it is asked for.
    const tools = page.locator("main details").filter({
      has: page.locator("summary", { hasText: MESSAGES[language].leagueMembers.decisionTools }),
    });
    await expect(tools).not.toHaveAttribute("open");
    await tools.locator(":scope > summary").click();
    const pin = page.getByRole("button", {
      name: tr ? "Bu planı karşılaştırmaya ekle" : "Pin this plan",
    });
    await expect(pin).toBeEnabled();
    await pin.click();
    // On a phone the plan's window is in the drawer.
    await page.getByRole("button", { name: MESSAGES[language].shell.openMenu }).click();
    await page.getByRole("radio", { name: /^5 / }).click();
    await expect(page).toHaveURL(/window=5/);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(pin).toBeEnabled();
    await pin.click();
    const first = page.getByRole("region", { name: "Plan A", exact: true });
    await first.getByRole("radio").check();
    const note = page.getByRole("textbox", {
      name: tr ? "Bu planı neden tercih ettim?" : "Why do I prefer this plan?",
    });
    await note.fill("Wait for the press conference; keep a transfer.");
    await page.reload();
    await tools.locator(":scope > summary").click();
    await expect(first.getByRole("radio")).toBeChecked();
    await expect(note).toHaveValue("Wait for the press conference; keep a transfer.");
    await expect(page.getByRole("region", { name: "Plan B", exact: true })).toBeVisible();
    await first.getByRole("button", { name: tr ? "Ayarlarını aç" : "Open settings" }).click();
    await expect(page).toHaveURL(/window=3/);
    await expect(
      page.getByRole("button", { name: tr ? "Bu plan eklendi" : "Plan pinned" }),
    ).toBeDisabled();
    expect(posts).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    const results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? "")),
    ).toEqual([]);
    await first.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`decision-board-${language}.png`) });
    await first.getByRole("button", { name: tr ? "Kaldır" : "Remove" }).click();
    await expect(note).toHaveCount(0);
  });
}
