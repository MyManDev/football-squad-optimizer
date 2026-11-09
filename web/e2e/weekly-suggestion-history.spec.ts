import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { atRest } from "./atRest";
import fixture from "../src/fixtures/weeklySuggestionHistory.json" with { type: "json" };
import recordedPlans from "../src/fixtures/recordedPlanRows.json" with { type: "json" };
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";
import { mockSuggestionOverview } from "../src/fixtures/weeklySuggestionOverview";

// Every test reads the example league, never the shipped tree: the history it routes is
// read through the tree the gate finds, which moves when the site publishes a directory.
test.beforeEach(async ({ page }) => {
  await installLeagueMocks(page);
});

for (const language of ["tr", "en"] as const) {
  test(`the suggested move expands without inventing settled scores in ${language}`, async ({
    page,
  }) => {
    const historyDocument = structuredClone(fixture);
    const [plain, , chip] = recordedPlans;
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
      // The plain plan stands last, behind the week's plans under a setting, a word, a chip and
      // a rival, each with a captain of its own, so the card cannot show one of them unseen.
      recorded_plans: [
        {
          ...settingOnly,
          published_path: "advice/101/saf-puan/1/top100-30.json",
          top100_weight: 30,
          captain: "Player 3",
        },
        {
          ...plain,
          published_path: "advice/101/saf-puan/1/hoca-sozu.json",
          managers_word: true,
          captain: "Player 4",
        },
        { ...chip, captain: "Player 5" },
        {
          ...plain,
          published_path: "advice/101/ortak-koru/1/vs-102.json",
          strategy: "ortak-koru",
          rival_entry_id: 102,
          captain: "Player 6",
        },
        { ...plain, moves: [{ player_out: "Player 2", player_in: "#18" }] },
      ],
    });
    // An earlier week whose plain plan moves nobody.
    historyDocument.payload.weeks.push(
      Object.assign({}, historyDocument.payload.weeks[0], { gameweek: 3, recorded_plans: [plain] }),
    );
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.route("**/data/league/history/101.json", (route) =>
      route.fulfill({ json: historyDocument }),
    );
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/league/352490/members/101/history");
    await page.getByRole("combobox").selectOption("4");
    const { suggestionHistory: copy, leagueMembers, decision } = MESSAGES[language];
    const details = page
      .locator("details")
      .filter({ has: page.getByText(copy.recordedPlans, { exact: true }) });
    await expect(details).not.toHaveAttribute("open");
    await expect(page.getByRole("table")).toHaveCount(0);
    await details.locator("summary").click();
    await expect(
      details.getByText(`${leagueMembers.strategies["saf-puan"].name}, ${decision.week(1)}`),
    ).toBeVisible();
    await expect(details.getByText(`${copy.captain}: Player 8`)).toBeVisible();
    await expect(details.getByRole("listitem")).toHaveText([
      `${leagueMembers.out}: Player 2; ${leagueMembers.in}: #18`,
    ]);
    await expect(details).not.toContainText(copy.noRecordedMoves);
    for (const other of ["Player 1", "#17", "Player 3", "Player 4", "Player 5", "Player 6"]) {
      await expect(details).not.toContainText(other);
    }
    // The shell clips sideways overflow, so the page's own scroll width cannot show a line that
    // runs past the column; the column's can.
    expect(
      await page.locator("main").evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);
    await page.reload();
    await page.getByRole("combobox").selectOption("4");
    await expect(details).not.toHaveAttribute("open");
    await page.getByRole("combobox").selectOption("3");
    await details.locator("summary").click();
    await expect(details.getByText(copy.noRecordedMoves, { exact: true })).toBeVisible();
    await expect(details.getByRole("listitem")).toHaveCount(0);
  });
}

test("member can open recorded history and inspect the Python-scored result on mobile", async ({
  page,
}, testInfo) => {
  const historyDocument = structuredClone(fixture);
  historyDocument.payload.entry_id = 35249001;
  await page.route("**/data/league/history/35249001.json", (route) =>
    route.fulfill({ json: historyDocument }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/league/352490/members/35249001");
  await page.getByRole("link", { name: "Haftalık öneri geçmişi" }).click();
  await expect(page).toHaveURL(/\/35249001\/history$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Haftalık öneri geçmişi");
  await page.getByRole("combobox", { name: "Hafta" }).selectOption("4");
  await expect(page.getByText("Fark:")).toContainText("−2,0");
  await expect(page.getByRole("row", { name: /Player 8 MID/ })).toContainText("Kaptan (x2)");
  expect(
    await page.locator("main").evaluate((element) => element.scrollWidth <= element.clientWidth),
  ).toBe(true);
  await atRest(page);
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
  await page.goto("/league/352490/members/101/history");
  await page.getByRole("combobox", { name: "Hafta" }).selectOption("4");
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
  await expect(page.getByText("Geçmiş okunamadı", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Yeniden dene" })).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
});

test("overview accumulates weeks, preserves totals while scrolling and opens weekly detail", async ({
  page,
}, testInfo) => {
  await page.route("**/data/league/history/101.json", (route) =>
    route.fulfill({ json: mockSuggestionOverview() }),
  );
  await page.goto("/league/352490/members/101/history");
  const overview = page.getByRole("region", { name: "Genel bakış" });
  await expect(overview.getByRole("row", { name: /^Toplam/ })).toContainText("624,0");
  await expect(overview.getByRole("row", { name: /^Toplam/ })).toContainText("610,0");
  await expect(overview.getByRole("row", { name: /^Toplam/ })).toContainText("+14,0");
  // The week buttons print a short word, and their names start with it (WCAG 2.5.3). The rule
  // is experimental, so axe runs it only when asked.
  await atRest(page);
  expect(
    (await new AxeBuilder({ page }).withRules(["label-content-name-mismatch"]).analyze())
      .violations,
  ).toEqual([]);
  await expect(
    overview
      .getByRole("row")
      .filter({ has: page.getByRole("button", { name: "OH4, Oyun haftası 4", exact: true }) }),
  ).toContainText("−2,0");
  await expect(
    overview
      .getByRole("row")
      .filter({ has: page.getByRole("button", { name: "OH5, Oyun haftası 5", exact: true }) }),
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
  await expect(page.getByText("Fark:")).toContainText("+6,0");
  await page.getByRole("combobox").selectOption("overview");
  await page.setViewportSize({ width: 390, height: 844 });
  await overview.evaluate((element) => {
    element.scrollLeft = element.scrollWidth;
  });
  await expect(
    overview.getByRole("button", { name: "OH4, Oyun haftası 4", exact: true }),
  ).toBeInViewport();
  expect(
    await page.locator("main").evaluate((element) => element.scrollWidth <= element.clientWidth),
  ).toBe(true);
  await atRest(page);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("overview-mobile.png"), fullPage: true });
});
