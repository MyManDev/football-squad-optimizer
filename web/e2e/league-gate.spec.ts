import { expect, test, type Page } from "@playwright/test";

import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";
import { NO_LEAGUE, REMEMBERED_LEAGUE_KEY } from "./leagueState";

// A first visit: no league remembered, so every league address is behind the number.
test.use({ storageState: NO_LEAGUE });

const member = mockLeagueMembersEnvelope.payload.members[0];
// The number connects only through a live publication; the fixture is served as one.
const published = { ...mockLeagueMembersEnvelope, source_kind: "live" };

async function servePublished(page: Page) {
  await installLeagueMocks(page);
  await page.route("**/data/league/members.json", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(published) }),
  );
}

for (const language of ["tr", "en"] as const) {
  const entry = MESSAGES[language].leagueEntry;

  test(`a direct member link asks for the league number first in ${language}`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    await servePublished(page);
    const address = `/league/members/${member.entry_id}`;
    await page.goto(address);

    // The form stands at the member's address; nothing of the league is on the page.
    await expect(page.getByRole("heading", { name: entry.title })).toBeVisible();
    await expect(page).toHaveURL(address);
    await expect(page.getByText(member.manager_name!)).toHaveCount(0);

    await page.getByLabel(entry.label).fill(String(mockLeagueMembersEnvelope.payload.league_id));
    await page.getByRole("button", { name: entry.submit }).click();

    // The member page opens where the visitor stood, and the number is kept for next time.
    await expect(page.getByRole("heading", { level: 1, name: member.team_name! })).toBeVisible();
    await expect(page).toHaveURL(address);
    expect(await page.evaluate((key) => localStorage.getItem(key), REMEMBERED_LEAGUE_KEY)).toBe(
      String(mockLeagueMembersEnvelope.payload.league_id),
    );

    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: member.team_name! })).toBeVisible();
    await expect(page.getByRole("heading", { name: entry.title })).toHaveCount(0);
  });

  test(`the members list and the league page are behind the number too in ${language}`, async ({
    page,
  }) => {
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    await servePublished(page);
    for (const address of ["/league/members", "/league"]) {
      await page.goto(address);
      await expect(page.getByRole("heading", { name: entry.title })).toBeVisible();
      await expect(page.getByText(member.manager_name!)).toHaveCount(0);
      await expect(page).toHaveURL(address);
    }
  });
}
