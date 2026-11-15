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
    // One statement: no region and no heading of its own, both saying the same sentence.
    await expect(
      page.getByRole("status").filter({ hasText: copy.deadlinePassedTitle }),
    ).toBeVisible();
    await expect(page.getByRole("region", { name: copy.deadlinePassedTitle })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: copy.deadlinePassedTitle })).toHaveCount(0);
    await expect(page.getByTestId("deadline-passed")).toContainText(copy.deadlinePassedTitle);
    // The current team stays visible; the closed week's computation remains locked.
    const member = MESSAGES[language].leagueMembers;
    await expect(page.getByRole("heading", { name: member.memberSquad })).toBeVisible();
    await expect(page.locator('#kadro [data-points-kind="expected"]')).toHaveCount(0);
    await expect(page.locator("#plan-settings")).toHaveCount(0);
    await expect(page.getByRole("link", { name: member.changePlan, exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: member.computeButton, exact: true })).toHaveCount(
      0,
    );
    // A closed week counts down to nothing and offers nothing to apply.
    await expect(page.getByTestId("deadline-countdown")).toHaveCount(0);
    await expect(page.getByRole("link", { name: member.applyOnFpl })).toHaveCount(0);
  });

  // On a rival's page the phone's top bar is the only place the team is named.
  test(`a closed gameweek prints the team's name whole on a phone in ${language}`, async ({
    page,
  }) => {
    await installLeagueMocks(page);
    const calendar = openCalendar();
    calendar.payload.gameweeks[0]!.deadline_utc = "2020-01-01T00:00:00Z";
    await page.route("**/data/fixtures.json", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(calendar) }),
    );
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.goto(`/league/352490/members/${ENTRY}`);

    const name = page.getByRole("heading", { level: 1 });
    await expect(name).toBeVisible();
    for (const width of [320, 340, 360, 390, 430]) {
      await page.setViewportSize({ width, height: 800 });
      const whole = await name.evaluate((element) => element.scrollWidth <= element.clientWidth);
      expect(whole, `the name at ${width} px`).toBe(true);
    }
  });
}

// The LIVE tag ends the score bug's line, so the team keeps the first line's room.
test("an open gameweek keeps the team's name its first line beside the LIVE tag on a phone", async ({
  page,
}) => {
  // Six days and 23 hours before the mocked deadline, so the countdown reads as a week's does.
  await page.clock.install({
    time: Date.parse("2999-01-01T00:00:00Z") - (6 * 24 + 23) * 3_600_000,
  });
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  await page.goto(`/league/352490/members/${ENTRY}`);
  const name = page.getByRole("heading", { level: 1 });
  const live = page.locator("[data-live-link]");
  await expect(page.getByTestId("deadline-countdown")).toBeVisible();
  for (const width of [320, 375, 390]) {
    await page.setViewportSize({ width, height: 800 });
    const [title, tag] = [(await name.boundingBox())!, (await live.boundingBox())!];
    // The tag stands below the name's line, inside the screen; the line keeps its 22 px.
    expect(tag.y, `the tag at ${width} px`).toBeGreaterThanOrEqual(title.y + title.height);
    expect(tag.x + tag.width).toBeLessThanOrEqual(width);
    expect(Math.round(title.height)).toBe(22);
    // "North Stand Notes" printed whole from 375 px before the tag, and still does.
    if (width >= 375) {
      const whole = await name.evaluate((element) => element.scrollWidth <= element.clientWidth);
      expect(whole, `the name at ${width} px`).toBe(true);
    }
  }
});

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

test("a member page already open closes at the deadline", async ({ page }) => {
  const deadline = new Date("2026-09-18T17:30:00Z");
  await page.clock.install({ time: new Date(deadline.getTime() - 70_000) });
  await installLeagueMocks(page);
  await serveTransfer(page);
  const calendar = openCalendar();
  calendar.payload.gameweeks[0]!.deadline_utc = deadline.toISOString();
  await page.route("**/data/fixtures.json", (route) => route.fulfill({ json: calendar }));
  await page.goto(`/league/352490/members/${ENTRY}`);

  const copy = MESSAGES.tr.leagueMembers;
  const settings = page.locator("#plan-settings");
  const apply = page.getByRole("link", { name: copy.applyOnFpl });
  await expect(settings).toBeVisible();
  await expect(apply).toBeVisible();

  await page.clock.pauseAt(new Date(deadline.getTime() - 20_000));
  await page.clock.runFor(19_999);
  await expect(page.getByTestId("deadline-passed")).toHaveCount(0);
  await expect(settings).toBeVisible();

  await page.clock.runFor(1);
  await expect(page.getByTestId("deadline-passed")).toBeVisible();
  await expect(settings).toHaveCount(0);
  await expect(apply).toHaveCount(0);
  await expect(page.getByRole("heading", { name: copy.memberSquad })).toBeVisible();
});
