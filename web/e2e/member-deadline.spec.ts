import { expect, test } from "@playwright/test";

import { COMPUTE_COPY } from "../src/features/league/advice/computeCopy";
import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { installLeagueMocks, openCalendar } from "./leagueMocks";

const ENTRY = 35249001;

for (const language of ["tr", "en"] as const) {
  test(`a closed gameweek is named and Compute is withheld in ${language}`, async ({ page }) => {
    await installLeagueMocks(page);
    const calendar = openCalendar();
    calendar.payload.gameweeks[0]!.deadline_utc = "2020-01-01T00:00:00Z";
    // Routes registered later win, so this calendar replaces the open one.
    await page.route("**/data/fixtures.json", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(calendar) }),
    );
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.goto(`/league/members/${ENTRY}`);

    const copy = COMPUTE_COPY[language];
    await expect(page.getByRole("heading", { name: copy.deadlinePassedTitle })).toBeVisible();
    const notice = page.getByTestId("deadline-passed");
    await expect(notice).toContainText(String(mockLeagueMembersEnvelope.payload.gameweek));
    await expect(notice).toContainText("2020");
    await expect(page.getByText(copy.deadlinePassedCompute, { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /^(Hesapla|Compute)$/ })).toBeDisabled();
  });
}

test("an open gameweek shows no deadline notice", async ({ page }) => {
  await installLeagueMocks(page);
  await page.goto(`/league/members/${ENTRY}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("deadline-passed")).toHaveCount(0);
});
