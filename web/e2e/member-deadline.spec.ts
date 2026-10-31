import { expect, test, type Page } from "@playwright/test";

import { COMPUTE_COPY } from "../src/features/league/advice/computeCopy";
import { mockEntryAdviceEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks, openCalendar } from "./leagueMocks";

const ENTRY = 35249001;

/** The mocked plan with a transfer in it, so the decision has something to apply on FPL. */
async function serveTransfer(page: Page) {
  const plan = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
  const { moves, expected_gain_vs_hold } = mockEntryAdviceEnvelope(ENTRY, "agresif", 1).payload;
  await page.route(`**/data/league/advice/${ENTRY}/saf-puan/1.json`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...plan, payload: { ...plan.payload, moves, expected_gain_vs_hold } }),
    }),
  );
}

for (const language of ["tr", "en"] as const) {
  test(`a closed gameweek is named and its settings are left out in ${language}`, async ({
    page,
  }) => {
    await installLeagueMocks(page);
    await serveTransfer(page);
    const calendar = openCalendar();
    calendar.payload.gameweeks[0]!.deadline_utc = "2020-01-01T00:00:00Z";
    // Routes registered later win, so this calendar replaces the open one.
    await page.route("**/data/fixtures.json", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(calendar) }),
    );
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.goto(`/league/352490/members/${ENTRY}`);

    const copy = COMPUTE_COPY[language];
    await expect(page.getByRole("heading", { name: copy.deadlinePassedTitle })).toBeVisible();
    await expect(page.getByTestId("deadline-passed")).toContainText(copy.deadlinePassedTitle);
    // The closed week's plan is still the answer; nothing that changes or recomputes it is
    // offered: no settings, no link down to them, no Hesapla and no model comparison.
    const member = MESSAGES[language].leagueMembers;
    await expect(page.getByRole("heading", { name: member.squadAfterTitle })).toBeVisible();
    await expect(page.locator("#plan-settings")).toHaveCount(0);
    await expect(page.getByRole("link", { name: member.changePlan, exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: member.computeButton, exact: true })).toHaveCount(
      0,
    );
    await expect(page.getByText(copy.deadlinePassedCompute, { exact: true })).toHaveCount(0);
    await expect(page.getByText(/^(Diğer modeli de hesapla|Compute the other model)$/)).toHaveCount(
      0,
    );
    // A closed week counts down to nothing and offers nothing to apply.
    await expect(page.getByTestId("deadline-countdown")).toHaveCount(0);
    await expect(page.getByRole("link", { name: member.applyOnFpl })).toHaveCount(0);
  });
}

test("an open gameweek shows no deadline notice, counts down and links to FPL", async ({
  page,
}) => {
  await installLeagueMocks(page);
  await serveTransfer(page);
  await page.goto(`/league/352490/members/${ENTRY}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("deadline-passed")).toHaveCount(0);
  await expect(page.locator("#plan-settings")).toBeVisible();
  await expect(page.getByTestId("deadline-countdown")).toBeVisible();
  const link = page.getByRole("link", { name: MESSAGES.tr.leagueMembers.applyOnFpl });
  await expect(link).toHaveAttribute("href", "https://fantasy.premierleague.com/transfers");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
});
