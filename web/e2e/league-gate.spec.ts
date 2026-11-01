import { expect, test, type Page } from "@playwright/test";

import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { exampleMember, pickMember } from "./identity";
import { installLeagueMocks } from "./leagueMocks";
import { NO_LEAGUE, REMEMBERED_LEAGUE_KEY } from "./leagueState";

const member = mockLeagueMembersEnvelope.payload.members[0];
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
// The number connects only through a live publication; the fixture is served as one.
const published = { ...mockLeagueMembersEnvelope, source_kind: "live" };

/** The published league, and a visitor who has not yet said who they are. */
async function servePublished(page: Page) {
  await installLeagueMocks(page, { claim: null });
  await page.route("**/data/league/members.json", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(published) }),
  );
}

test.describe("a first visit", () => {
  // No league remembered, so every league address is behind the number.
  test.use({ storageState: NO_LEAGUE });

  for (const language of ["tr", "en"] as const) {
    const entry = MESSAGES[language].leagueEntry;
    const picker = MESSAGES[language].memberPicker;

    test(`an unpublished address keeps its number and another valid league remains usable in ${language}`, async ({
      page,
    }) => {
      await page.addInitScript(
        ({ language, league }) => {
          localStorage.setItem("squadopt.language", language);
          localStorage.setItem("squadopt.league", String(league));
        },
        { language, league: LEAGUE },
      );
      await servePublished(page);
      await page.route("**/data/leagues.json", (route) =>
        route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            contract_version: "league_directory_v1",
            payload: {
              leagues: [
                null,
                {
                  league_id: LEAGUE,
                  league_name: published.payload.league_name,
                  season: published.payload.season,
                  gameweek: published.payload.gameweek,
                  path: "league",
                },
              ],
            },
          }),
        }),
      );
      const address = `/league/123456/members/${member.entry_id}?mode=saf-puan`;
      await page.goto(address);
      await expect(page.getByLabel(entry.label)).toHaveValue("123456");
      // The league is not listed, so the gate asks the forwarder, which no spec here runs.
      await expect(page.getByRole("status")).toHaveText(entry.cannotOpen(123456));
      await expect(page).toHaveURL(address);
      expect(await page.evaluate(() => localStorage.getItem("squadopt.league"))).toBe(
        String(LEAGUE),
      );

      await page.getByLabel(entry.label).fill(String(LEAGUE));
      await page.getByRole("button", { name: entry.submit }).click();
      await expect(page.getByRole("heading", { level: 1, name: picker.title })).toBeVisible();
      await expect(page).toHaveURL(`/league/${LEAGUE}/members`);
    });

    test(`a direct link from before the league number asks for the number first in ${language}`, async ({
      page,
    }) => {
      await page.addInitScript(
        (value) => localStorage.setItem("squadopt.language", value),
        language,
      );
      await servePublished(page);
      const address = `/league/members/${member.entry_id}`;
      await page.goto(address);

      // The form stands at the member's address; nothing of the league is on the page.
      await expect(page.getByRole("heading", { name: entry.title })).toBeVisible();
      await expect(page).toHaveURL(address);
      await expect(page.getByText(member.manager_name!)).toHaveCount(0);

      await page.getByLabel(entry.label).fill(String(LEAGUE));
      await page.getByRole("button", { name: entry.submit }).click();

      // The address is rewritten under the league's number, and the visitor is asked who
      // they are there; the number is kept for next time.
      const numbered = `/league/${LEAGUE}/members/${member.entry_id}`;
      await expect(page.getByRole("heading", { level: 1, name: picker.title })).toBeVisible();
      await expect(page).toHaveURL(numbered);
      await pickMember(page, exampleMember(member.entry_id!), language);
      // The member page opens where the visitor stood.
      await expect(page.getByRole("heading", { level: 1, name: member.team_name! })).toBeVisible();
      await expect(page).toHaveURL(numbered);
      expect(await page.evaluate((key) => localStorage.getItem(key), REMEMBERED_LEAGUE_KEY)).toBe(
        String(LEAGUE),
      );

      await page.reload();
      await expect(page.getByRole("heading", { level: 1, name: member.team_name! })).toBeVisible();
      await expect(page).toHaveURL(numbered);
      await expect(page.getByRole("heading", { name: entry.title })).toHaveCount(0);
    });

    test(`a numbered member link asks who you are, not for the number, in ${language}`, async ({
      page,
    }) => {
      await page.addInitScript(
        (value) => localStorage.setItem("squadopt.language", value),
        language,
      );
      await servePublished(page);
      const address = `/league/${LEAGUE}/members/${member.entry_id}`;
      await page.goto(address);
      await expect(page.getByRole("heading", { level: 1, name: picker.title })).toBeVisible();
      await expect(page).toHaveURL(address);
      await expect(page.getByRole("heading", { name: entry.title })).toHaveCount(0);
      await expect(page.getByRole("heading", { level: 1, name: member.team_name! })).toHaveCount(0);
      // The league in the address is the one the visitor is in from here on.
      expect(await page.evaluate((key) => localStorage.getItem(key), REMEMBERED_LEAGUE_KEY)).toBe(
        String(LEAGUE),
      );
    });

    test(`the members list and the league page from before the number are behind it too in ${language}`, async ({
      page,
    }) => {
      await page.addInitScript(
        (value) => localStorage.setItem("squadopt.language", value),
        language,
      );
      await servePublished(page);
      for (const address of ["/league/members", "/league"]) {
        await page.goto(address);
        await expect(page.getByRole("heading", { name: entry.title })).toBeVisible();
        await expect(page.getByText(member.manager_name!)).toHaveCount(0);
        await expect(page).toHaveURL(address);
      }
    });

    test(`an address naming a league the site does not publish shows the form in place in ${language}`, async ({
      page,
    }) => {
      await page.addInitScript(
        (value) => localStorage.setItem("squadopt.language", value),
        language,
      );
      await servePublished(page);
      const address = `/league/123456/members/${member.entry_id}`;
      await page.goto(address);
      await expect(page.getByRole("heading", { name: entry.title })).toBeVisible();
      await expect(page).toHaveURL(address);
      await expect(page.getByText(member.manager_name!)).toHaveCount(0);
    });
  }
});

test.describe("a return visit", () => {
  // The default browser state: the published league was opened by its number before.
  for (const language of ["tr", "en"] as const) {
    const entry = MESSAGES[language].leagueEntry;
    const picker = MESSAGES[language].memberPicker;

    test(`an address from before the league number is rewritten to the remembered league's in ${language}`, async ({
      page,
    }) => {
      await page.addInitScript(
        (value) => localStorage.setItem("squadopt.language", value),
        language,
      );
      await servePublished(page);
      await page.goto(`/league/members/${member.entry_id}?mode=saf-puan&window=3`);
      const numbered = `/league/${LEAGUE}/members/${member.entry_id}?mode=saf-puan&window=3`;
      await expect(page.getByRole("heading", { level: 1, name: picker.title })).toBeVisible();
      await expect(page).toHaveURL(numbered);
      await expect(page.getByRole("heading", { name: entry.title })).toHaveCount(0);
      // Onayla keeps the address, its plan included.
      await pickMember(page, exampleMember(member.entry_id!), language);
      await expect(page.getByRole("heading", { level: 1, name: member.team_name! })).toBeVisible();
      await expect(page).toHaveURL(numbered);

      await page.goto("/league/members");
      await expect(page).toHaveURL(`/league/${LEAGUE}/members`);
      // The members list's own link: the sidebar names the member too once claimed, and
      // the league race names every member.
      await expect(
        page.getByRole("main").getByRole("link", { name: member.manager_name!, exact: true }),
      ).toBeVisible();
    });
  }
});
