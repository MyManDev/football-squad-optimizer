import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fixture from "../src/fixtures/weeklySuggestionHistory.json" with { type: "json" };
import { installLeagueMocks } from "./leagueMocks";

test.beforeEach(async ({ page }) => {
  // These acceptance tests are offline; a remote font must not hold document load open.
  await page.route("https://fonts.googleapis.com/**", (route) =>
    route.fulfill({ contentType: "text/css", body: "" }),
  );
});

test("member can open recorded history and inspect the Python-scored result on mobile", async ({
  page,
}, testInfo) => {
  await installLeagueMocks(page);
  const historyDocument = structuredClone(fixture);
  historyDocument.payload.entry_id = 35249001;
  await page.route("**/data/league/history/35249001.json", (route) =>
    route.fulfill({ json: historyDocument }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/league/members/35249001");
  await page.getByRole("link", { name: "Haftalık öneri geçmişi" }).click();
  await expect(page).toHaveURL(/\/35249001\/history$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Haftalık öneri geçmişi");
  await expect(page.getByText("Önerinin neti − üyenin neti:")).toContainText("−2,0");
  await expect(page.getByRole("row", { name: /Player 8 MID/ })).toContainText("×2");
  await page.getByText("Kayıt ayrıntıları", { exact: true }).click();
  await expect(
    page.getByText(historyDocument.payload.weeks[0].advice_sha256, { exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("history-mobile.png"), fullPage: true });
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Haftalık öneri geçmişi");
});

test("unsettled, missing and invalid publications never display an invented comparison", async ({
  page,
}) => {
  const pending = structuredClone(fixture);
  Object.assign(pending.payload.weeks[0], {
    status: "unsettled",
    reason: "not_settled",
    suggested: null,
    actual: null,
    net_difference: null,
    players: [],
    outcome_snapshot_id: null,
    outcome_captured_at_utc: null,
  });
  await page.route("**/data/league/history/101.json", (route) => route.fulfill({ json: pending }));
  await page.goto("/league/members/101/history");
  await expect(page.getByText("Sonuç kesinleşmedi", { exact: true })).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
  await page.unroute("**/data/league/history/101.json");
  await page.route("**/data/league/history/101.json", (route) =>
    route.fulfill({ status: 404, body: "{}" }),
  );
  await page.reload();
  await expect(page.getByText("Kayıt yok", { exact: true })).toBeVisible();
  await page.unroute("**/data/league/history/101.json");
  await page.route("**/data/league/history/101.json", (route) =>
    route.fulfill({ json: { ...fixture, contract_version: "bad" } }),
  );
  await page.reload();
  await expect(page.getByText("Geçmiş doğrulanamadı", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Yeniden dene" })).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
});
