import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { MESSAGES } from "../src/i18n/messages";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { installLeagueMocks } from "./leagueMocks";

const apiOrigin = process.env.VITE_ADVICE_API_ORIGIN;

async function noSidewaysScroll(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
}

async function blocking(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
}

/** Opens the phone drawer and waits until it has finished sliding in. */
async function openDrawer(page: Page, language: "tr" | "en") {
  await page.getByRole("button", { name: MESSAGES[language].shell.openMenu }).click();
  await expect(page.locator("#sidebar")).toHaveCSS("transform", "none");
  return page.getByRole("dialog", { name: MESSAGES[language].shell.menu });
}

const ENTRY = 35249001;

/**
 * A calendar for the mocked member's week and the two after it, in which every club of
 * the example squad and plan plays: at home in the first week, away in the second, and
 * the first club twice in the third (a double week).
 */
function calendar() {
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const plan = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1).payload;
  const clubs = [
    ...new Set([...squad.starting_xi, ...(plan.starting_xi ?? [])].map((p) => p.team)),
  ];
  const side = (name: string, index: number) => ({
    team_id: index + 1,
    name,
    short_name: name.slice(0, 3).toUpperCase(),
  });
  const rival = { team_id: 99, name: "Visitors", short_name: "VIS" };
  const match = (id: number, home: ReturnType<typeof side>, away: ReturnType<typeof side>) => ({
    fixture_id: id,
    kickoff_utc: null,
    home,
    away,
    finished: false,
    home_score: null,
    away_score: null,
  });
  const teams = clubs.map(side);
  return {
    contract_version: "fixtures_v1",
    generated_at_utc: "2026-08-20T00:00:00Z",
    payload: {
      season: squad.season,
      source_snapshot_id: "fpl-live-mock",
      captured_at_utc: "2026-08-20T00:00:00Z",
      current_gameweek: squad.gameweek,
      unscheduled_count: 0,
      gameweeks: [
        {
          gameweek: squad.gameweek,
          deadline_utc: "2999-01-01T00:00:00Z",
          fixtures: teams.map((team, index) => match(index + 1, team, rival)),
        },
        {
          gameweek: squad.gameweek + 1,
          deadline_utc: "2999-01-08T00:00:00Z",
          fixtures: teams.map((team, index) => match(100 + index, rival, team)),
        },
        {
          gameweek: squad.gameweek + 2,
          deadline_utc: "2999-01-15T00:00:00Z",
          fixtures: [
            ...teams.map((team, index) => match(200 + index, team, rival)),
            match(300, rival, teams[0]!),
          ],
        },
      ],
    },
  };
}

for (const language of ["tr", "en"] as const) {
  test(`member page fits a phone, with the plan and Compute in the drawer, in ${language}`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await installLeagueMocks(page);
    await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.goto("/league/members/35249001?mode=saf-puan&window=3");
    const copy = MESSAGES[language];
    const members = copy.leagueMembers;

    // The decision names the selection it shows.
    const summary = page.getByTestId("member-selection-summary");
    await expect(summary).toContainText(copy.decision.week(3));
    await expect(summary).not.toContainText(members.top100Weight(0));
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath(`member-top-${language}.png`) });

    // What explains the plan, the squad held before the transfers and the secondary tools
    // wait closed, on a phone as on a desktop, and none of them widens the page when opened.
    const closedSections = [
      members.howComputed,
      members.memberSquad,
      members.advancedSettings,
      members.decisionTools,
      members.chipsAndTransfers,
    ];
    for (const title of closedSections) {
      const detail = page
        .locator("main details")
        .filter({ has: page.locator("summary", { hasText: title }) });
      await expect(detail).toHaveCount(1);
      await expect(detail).not.toHaveAttribute("open");
      await detail.locator(":scope > summary").click();
      await expect(detail).toHaveAttribute("open", "");
      expect(await noSidewaysScroll(page)).toBe(true);
      await detail.locator(":scope > summary").click();
    }
    // The squad section draws the plan's eleven upright on a phone, with the bench under it.
    const pitch = page.getByRole("list", { name: copy.squad.pitchLabel });
    await pitch.scrollIntoViewIfNeeded();
    await expect(pitch).toBeVisible();
    await expect(page.getByRole("region", { name: members.bench })).toBeVisible();
    expect(await noSidewaysScroll(page)).toBe(true);

    // The window plan lays each week out as a block instead of scrolling sideways, and
    // stays a table with its column names for a screen reader.
    const plan = page.getByRole("region", { name: members.windowTitle(3) });
    await expect(plan.locator("tbody tr")).toHaveCount(3);
    await expect(plan.getByRole("columnheader", { name: members.windowHits })).toBeAttached();
    await plan.scrollIntoViewIfNeeded();
    expect(
      await plan.evaluate((section) => {
        const table = section.querySelector("table")!;
        const edge = section.getBoundingClientRect().right + 1;
        return (
          table.scrollWidth <= table.clientWidth + 1 &&
          table.getBoundingClientRect().right <= edge &&
          [...table.querySelectorAll("tbody th, tbody td")].every(
            (cell) =>
              cell.getBoundingClientRect().right <= edge &&
              cell.scrollWidth <= cell.clientWidth + 1,
          )
        );
      }),
    ).toBe(true);
    // Every week's names are whole words on a line, not one letter per line.
    for (const row of await plan.locator("tbody tr").all()) {
      expect((await row.boundingBox())!.height).toBeLessThan(120);
    }
    expect(await noSidewaysScroll(page)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`member-window-${language}.png`) });

    // Nothing is pinned to the bottom of the phone page: the plan and Compute are in the
    // drawer, so no bottom scroll padding is left to make room for them.
    const compute = page.getByRole("button", { name: members.computeButton, exact: true });
    await expect(compute).toBeHidden();
    expect(
      await page.evaluate(() => getComputedStyle(document.documentElement).scrollPaddingBottom),
    ).toBe("auto");
    expect(await blocking(page)).toEqual([]);

    const drawer = await openDrawer(page, language);
    await expect(drawer.getByRole("radio", { name: /^3 / })).toBeChecked();
    await expect(drawer.getByRole("heading", { name: members.planTitle })).toBeVisible();
    await expect(drawer.locator("[data-compute-dock]")).toContainText(members.computeButton);
    await expect(compute).toBeInViewport({ ratio: 1 });
    const dock = (await page.locator("[data-compute-dock]").boundingBox())!;
    expect(dock.y + dock.height).toBeLessThanOrEqual(812 + 1);
    expect(await blocking(page)).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`member-drawer-${language}.png`) });

    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(compute).toBeHidden();
    expect(await noSidewaysScroll(page)).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`member-mobile-${language}.png`),
      fullPage: true,
    });

    // On a wide screen the plan and Compute are in the sidebar, and every section still
    // waits closed.
    await page.setViewportSize({ width: 1280, height: 900 });
    await expect(compute).toBeVisible();
    for (const title of closedSections) {
      await expect(
        page.locator("main details").filter({ has: page.locator("summary", { hasText: title }) }),
      ).not.toHaveAttribute("open");
    }
  });

  test(`Compute stays pinned at the foot of a short phone's drawer in ${language}`, async ({
    page,
  }) => {
    // iPhone SE with Safari's bars shown: the drawer's plan is taller than the screen.
    await page.setViewportSize({ width: 375, height: 548 });
    await installLeagueMocks(page);
    await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.goto("/league/members/35249001?mode=saf-puan&window=3");
    await openDrawer(page, language);
    const compute = page.getByRole("button", {
      name: MESSAGES[language].leagueMembers.computeButton,
      exact: true,
    });
    const body = page.locator("#sidebar [class*='body']").first();
    expect(await body.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(
      true,
    );
    for (const to of ["top", "bottom"] as const) {
      await body.evaluate((element, where) => {
        element.scrollTop = where === "top" ? 0 : element.scrollHeight;
      }, to);
      await expect(compute).toBeInViewport({ ratio: 1 });
    }
    await body.evaluate((element) => {
      element.scrollTop = 0;
    });
    // Scrolled to the top, the block with Compute sits on the drawer's bottom edge.
    await expect
      .poll(async () => {
        const box = await page.locator("[data-compute-dock]").boundingBox();
        return box ? Math.abs(box.y + box.height - 548) : 999;
      })
      .toBeLessThanOrEqual(1);
    expect(await blocking(page)).toEqual([]);
  });

  test(`a waiting computation stays compact and is echoed on the page in ${language}`, async ({
    page,
  }, testInfo) => {
    test.skip(
      !apiOrigin,
      "The build has no VITE_ADVICE_API_ORIGIN; a static build cannot enter a compute job.",
    );
    await page.setViewportSize({ width: 375, height: 667 });
    await installLeagueMocks(page);
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    const squad = mockEntrySquadEnvelopes[35249001]!.payload;
    await page.route("**/api/v1/**", async (route) => {
      const headers = {
        "access-control-allow-origin": new URL(page.url()).origin,
        "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-allow-headers": "content-type, idempotency-key",
      };
      if (route.request().method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers });
        return;
      }
      const url = route.request().url();
      const [status, body] = url.endsWith("/capabilities")
        ? [
            200,
            {
              contract_version: "league_capabilities_v1",
              league_id: squad.league_id,
              season: squad.season,
              gameweek: squad.gameweek,
              capture_snapshot_id: squad.source_snapshot_id,
              strategies: { "saf-puan": { windows: [1, 3, 5], requires_rival: false } },
              top100: { available: true, weights: [0, 20] },
              managers_word: { available: false },
            },
          ]
        : url.includes("/advice-jobs/")
          ? [200, { job_id: "mobile-waiting", status: "running" }]
          : route.request().method() === "POST"
            ? [202, { job_id: "mobile-waiting" }]
            : [404, { error: { code: "NOT_COMPUTED" } }];
      await route.fulfill({
        status: status as number,
        contentType: "application/json",
        headers,
        body: JSON.stringify(body),
      });
    });
    await page.goto("/league/members/35249001?window=3&top100=20");
    const copy = MESSAGES[language].leagueMembers;
    const drawer = await openDrawer(page, language);
    await drawer.getByRole("button", { name: copy.computeButton, exact: true }).click();
    const dock = page.locator("[data-compute-dock]");
    await expect(dock.getByText(copy.computeRunning, { exact: true })).toBeVisible();
    await expect(dock.getByText(copy.computeWaitingWithFallback, { exact: false })).toBeVisible();
    const box = (await dock.boundingBox())!;
    expect(box.height).toBeLessThanOrEqual(667 * 0.45 + 1);
    expect(box.y + box.height).toBeLessThanOrEqual(667 + 1);
    await page.screenshot({ path: testInfo.outputPath(`member-waiting-${language}.png`) });

    // Once the drawer closes, the page still says a computation is running.
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(
      page.locator("main").getByText(copy.computeEcho(copy.computeEchoStates.running), {
        exact: true,
      }),
    ).toBeVisible();
    expect(await noSidewaysScroll(page)).toBe(true);
  });

  test(`the fixtures open as a sheet over the page from the phone bar in ${language}`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 664 });
    await installLeagueMocks(page);
    await page.route("**/data/fixtures.json", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(calendar()) }),
    );
    await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.goto(`/league/members/${ENTRY}`);
    const copy = MESSAGES[language];
    await expect(page.getByTestId("member-selection-summary")).toBeVisible();

    // The sheet is off the screen until the phone bar's 'Fikstür' opens it.
    const open = page.getByRole("banner").getByRole("button", { name: copy.shell.fixtures });
    await expect(open).toHaveAttribute("aria-controls", "fixture-sheet");
    await expect(open).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByRole("dialog", { name: copy.shell.fixtures })).toHaveCount(0);
    await expect(page.locator("#fixture-sheet")).toBeHidden();

    await open.click();
    const sheet = page.getByRole("dialog", { name: copy.shell.fixtures });
    await expect(sheet).toBeVisible();
    await expect(page.locator("#fixture-sheet")).toHaveCSS("transform", "none");
    await expect(sheet).toHaveAttribute("aria-modal", "true");
    await expect(open).toHaveAttribute("aria-expanded", "true");
    const close = sheet.getByRole("button", { name: copy.shell.closeFixtures });
    await expect(close).toBeFocused();
    // It comes from the right, 350 px wide at most, as tall as the screen, above the scrim.
    const box = (await sheet.boundingBox())!;
    expect(box.x + box.width).toBeCloseTo(390, 0);
    expect(box.width).toBeLessThanOrEqual(350);
    expect(box.height).toBeCloseTo(664, 0);
    // The page behind is locked and out of reach.
    await expect(page.locator("main")).toHaveAttribute("inert", "");
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).toBe(
      "hidden",
    );
    // The eleven and the transfers, three gameweeks each, home filled and away outlined.
    const eleven = sheet.getByRole("region", { name: copy.leagueMembers.railXi });
    await expect(eleven.locator("tbody tr")).toHaveCount(11);
    await expect(eleven.locator("tbody tr").first().locator("td")).toHaveCount(3);
    await expect(eleven.locator('[data-venue="home"]').first()).toBeVisible();
    await expect(eleven.locator('[data-venue="away"]').first()).toBeVisible();
    await expect(sheet).toContainText(copy.leagueMembers.railLegendDifficulty);
    // Tab stays in the sheet.
    for (let step = 0; step < 6; step += 1) {
      await page.keyboard.press("Tab");
      expect(
        await page.evaluate(
          () =>
            document.activeElement === document.body ||
            !!document.activeElement?.closest("#fixture-sheet"),
        ),
      ).toBe(true);
    }
    expect(await blocking(page)).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`member-sheet-${language}.png`) });

    // Escape closes it and gives focus back to the phone bar's button.
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(open).toBeFocused();
    await expect(page.locator("main")).not.toHaveAttribute("inert");
    // So does its close button, and so does the scrim.
    await open.click();
    await expect(close).toBeFocused();
    await close.click();
    await expect(page.getByRole("dialog", { name: copy.shell.fixtures })).toHaveCount(0);
    await open.click();
    await expect(page.getByRole("dialog", { name: copy.shell.fixtures })).toBeVisible();
    await page.locator("[class*=scrim]").click({ position: { x: 16, y: 300 } });
    await expect(page.getByRole("dialog", { name: copy.shell.fixtures })).toHaveCount(0);
    expect(await noSidewaysScroll(page)).toBe(true);
  });
}
