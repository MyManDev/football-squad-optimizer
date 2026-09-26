import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fixture from "../src/fixtures/weeklySuggestionHistory.json" with { type: "json" };
import recordedPlans from "../src/fixtures/recordedPlanRows.json" with { type: "json" };
import { TOP100_COPY } from "../src/features/league/advice/top100Copy";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";
import { mockSuggestionOverview } from "../src/fixtures/weeklySuggestionOverview";

test.beforeEach(async ({ page }) => {
  // Nothing here reaches past the local preview: the one test that opens a member page
  // installs the league mocks, which refuse the advice API, and the remote font stylesheet
  // is answered empty so it cannot hold document load open.
  await page.route("https://fonts.googleapis.com/**", (route) =>
    route.fulfill({ contentType: "text/css", body: "" }),
  );
});

for (const language of ["tr", "en"] as const) {
  test(`recorded settings expand without inventing settled scores in ${language}`, async ({
    page,
  }) => {
    const historyDocument = structuredClone(fixture);
    // The fixture's Top 100 record without the manager's word.
    const settingOnly: Record<string, unknown> = { ...recordedPlans[1] };
    delete settingOnly.managers_word;
    Object.assign(historyDocument.payload.weeks[0], {
      status: "unsettled",
      reason: "not_settled",
      suggested: null,
      actual: null,
      net_difference: null,
      players: [],
      outcome_snapshot_id: null,
      outcome_captured_at_utc: null,
      recorded_plans: [
        ...recordedPlans,
        // A setting priced against a proven pure-points plan: its ceiling is its price.
        {
          ...settingOnly,
          published_path: "advice/101/saf-puan/1/top100-30.json",
          top100_weight: 30,
          moves: [],
          expected_points_cost: 1.5,
          expected_points_cost_ceiling: 1.5,
        },
      ],
    });
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.route("**/data/league/history/101.json", (route) =>
      route.fulfill({ json: historyDocument }),
    );
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/league/members/101/history");
    await page.getByRole("combobox").selectOption("4");
    const copy = MESSAGES[language].suggestionHistory;
    const details = page
      .locator("details")
      .filter({ has: page.getByText(copy.recordedPlans, { exact: true }) });
    await expect(details).not.toHaveAttribute("open");
    await expect(page.getByRole("table")).toHaveCount(0);
    await details.locator("summary").click();
    await expect(details.getByText(new RegExp(`${TOP100_COPY[language].legend} 20`))).toBeVisible();
    await expect(details.getByText(/Player 1/)).toBeVisible();
    await expect(details).toContainText("#17");
    const decimal = (value: string) => (language === "tr" ? value.replace(".", ",") : value);
    // The recorded price whose ceiling is its price is printed as the price.
    await expect(details).toContainText(TOP100_COPY[language].cost(decimal("1.5")));
    // The fixture's word-and-setting record carries a ceiling (4.0) above its price (2.5),
    // which only a price measured against an unproven pure-points plan ever did: that
    // figure bounds nothing, so neither number is printed for it.
    await expect(details).not.toContainText(
      TOP100_COPY[language].combinedCostAtMost(decimal("4.0")),
    );
    await expect(details).not.toContainText(TOP100_COPY[language].combinedCost(decimal("2.5")));
    await expect(details).not.toContainText(decimal("4.0"));
    await expect(details).not.toContainText(decimal("2.5"));
    await expect(details).toContainText(MESSAGES[language].leagueMembers.chipNames.bboost);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.reload();
    await page.getByRole("combobox").selectOption("4");
    await expect(details).not.toHaveAttribute("open");
  });
}

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
  await page.getByRole("combobox", { name: "Kayıtlı hafta" }).selectOption("4");
  await expect(page.getByText("Önerinin neti − üyenin neti:")).toContainText("−2,0");
  await expect(page.getByRole("row", { name: /Player 8 MID/ })).toContainText("Kaptan (x2)");
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
  await page.getByRole("combobox", { name: "Kayıtlı hafta" }).selectOption("4");
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

test("overview accumulates weeks, preserves totals while scrolling and opens weekly detail", async ({
  page,
}, testInfo) => {
  await page.route("**/data/league/history/101.json", (route) =>
    route.fulfill({ json: mockSuggestionOverview() }),
  );
  await page.goto("/league/members/101/history");
  const overview = page.getByRole("region", { name: "Genel bakış" });
  await expect(overview.getByRole("row", { name: /^Toplam/ })).toContainText("624,0");
  await expect(overview.getByRole("row", { name: /^Toplam/ })).toContainText("610,0");
  await expect(overview.getByRole("row", { name: /^Toplam/ })).toContainText("+14,0");
  await expect(
    overview
      .getByRole("row")
      .filter({ has: page.getByRole("button", { name: "Oyun haftası 4", exact: true }) }),
  ).toContainText("−2,0");
  await expect(
    overview
      .getByRole("row")
      .filter({ has: page.getByRole("button", { name: "Oyun haftası 5", exact: true }) }),
  ).toContainText("+4,0");
  expect(await overview.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(
    true,
  );
  await overview.scrollIntoViewIfNeeded();
  await overview.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect(overview.getByRole("button", { name: "Oyun haftası 14" })).toBeVisible();
  await expect(overview.getByRole("rowheader", { name: "Toplam", exact: true })).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath("overview-desktop.png"), fullPage: true });
  await page.getByRole("combobox").selectOption("5");
  await expect(page.getByText("Önerinin neti − üyenin neti:")).toContainText("+6,0");
  await page.getByRole("combobox").selectOption("overview");
  await page.setViewportSize({ width: 390, height: 844 });
  await overview.evaluate((element) => {
    element.scrollLeft = element.scrollWidth;
  });
  await expect(overview.getByRole("button", { name: "Oyun haftası 4" })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("overview-mobile.png"), fullPage: true });
});
