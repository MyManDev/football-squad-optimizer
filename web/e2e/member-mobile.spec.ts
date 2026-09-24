import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { MESSAGES } from "../src/i18n/messages";
import { mockEntrySquadEnvelopes } from "../src/fixtures/league";
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

    // What explains the plan and the secondary tools wait closed, on a phone as on a
    // desktop, and none of them widens the page when opened.
    const closedSections = [
      members.howComputed,
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
    // The held squad stays folded on a phone until its place under the pitch.
    const held = page
      .locator("main details")
      .filter({ has: page.locator("summary", { hasText: members.memberSquad }) });
    await expect(held).not.toHaveAttribute("open");

    // The window plan wraps its cells instead of scrolling sideways.
    const plan = page.getByRole("region", { name: members.windowTitle(3) });
    await expect(plan.locator("tbody tr")).toHaveCount(3);
    await plan.scrollIntoViewIfNeeded();
    expect(
      await plan.evaluate((section) => {
        const table = section.querySelector("table")!;
        return (
          table.scrollWidth <= table.clientWidth + 1 &&
          table.getBoundingClientRect().right <= section.getBoundingClientRect().right + 1
        );
      }),
    ).toBe(true);
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

    // A wide screen opens the held squad by itself; the tools stay closed there too.
    await page.setViewportSize({ width: 1280, height: 900 });
    await expect(held).toHaveAttribute("open", "");
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
}
