import { expect, test } from "@playwright/test";

import { COMPUTE_COPY } from "../src/features/league/advice/computeCopy";
import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks, openCalendar } from "./leagueMocks";

const ENTRY = 35249001;

for (const language of ["tr", "en"] as const) {
  test(`a closed gameweek is named and its settings are left out in ${language}`, async ({
    page,
  }) => {
    await installLeagueMocks(page);
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
    const notice = page.getByTestId("deadline-passed");
    await expect(notice).toContainText(String(mockLeagueMembersEnvelope.payload.gameweek));
    await expect(notice).toContainText("2020");
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
  });
}

test("an open gameweek shows no deadline notice", async ({ page }) => {
  await installLeagueMocks(page);
  await page.goto(`/league/352490/members/${ENTRY}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("deadline-passed")).toHaveCount(0);
  await expect(page.locator("#plan-settings")).toBeVisible();
});
