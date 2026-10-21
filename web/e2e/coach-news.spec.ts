import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mockEntryAdviceIndex } from "../src/fixtures/league";
import { coachNewsFixture, NEWS_ENTRY } from "../src/testSupport/coachNews";
import { installLeagueMocks } from "./leagueMocks";

// Synthetic transport fixtures exercise the UI, never the live provider.
for (const width of [360, 1280]) {
  test(`verified absence has a readable quote and source at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installLeagueMocks(page);
    const { squad, document: newsDocument, item } = coachNewsFixture();
    const bench = squad.payload.bench[0]!;
    newsDocument.payload.evidence!.applied.push({
      ...item,
      player_id: bench.player_id,
      name: bench.name,
    });
    const index = mockEntryAdviceIndex(NEWS_ENTRY);
    const path = `advice/${NEWS_ENTRY}/saf-puan/1/hoca-sozu.json`;
    index.payload.evidence = {
      available: true,
      path,
      applied_count: 2,
      source_kind: "club_news_capture",
      source_label: "synthetic-test-capture",
      clubs_covered: ["Liverpool"],
      rule_version: "managers_word_rule_v3",
      binding: true,
    };
    await page.route(`**/data/league/advice/${NEWS_ENTRY}/index.json`, (route) =>
      route.fulfill({ json: index }),
    );
    await page.route(`**/data/league/${path}`, (route) => route.fulfill({ json: newsDocument }));
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
    await page.goto(`/league/352490/members/${NEWS_ENTRY}?mode=saf-puan&window=1&llm=off`);
    const news = page.getByRole("region", { name: "Hocanın açıklaması" });
    await expect(news).toBeVisible();
    await expect(news.getByText(item.words!, { exact: true })).toHaveCount(2);
    await expect(news.getByRole("link", { name: "Haberi oku" }).first()).toHaveAttribute(
      "href",
      item.source_url!,
    );
    await expect(page.locator("#kadro [data-coach-absence]")).toHaveCount(2);
    const geometry = await page.locator("#kadro").evaluate((section) => ({
      width: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth,
      links: [...section.querySelectorAll("[data-coach-absence]")].map((link) => {
        const box = link.getBoundingClientRect();
        const plate = link.parentElement!.parentElement!.getBoundingClientRect();
        return {
          width: box.width,
          height: box.height,
          inside: box.left >= plate.left && box.right <= plate.right,
        };
      }),
    }));
    expect(geometry.scroll).toBeLessThanOrEqual(geometry.width);
    for (const link of geometry.links) {
      expect(link.width).toBeGreaterThanOrEqual(24);
      expect(link.height).toBeGreaterThanOrEqual(24);
      expect(link.inside).toBe(true);
    }
    const axe = await new AxeBuilder({ page }).include("#kadro").analyze();
    expect(axe.violations).toEqual([]);
    await page.locator("#kadro").screenshot({ path: `test-results/coach-news-${width}.png` });
  });
}
