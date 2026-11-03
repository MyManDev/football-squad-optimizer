import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { COMPUTE_COPY } from "../src/features/league/advice/computeCopy";
import { mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { MESSAGES, type Language } from "../src/i18n/messages";
import { atRest } from "./atRest";
import { installLeagueMocks } from "./leagueMocks";

const apiOrigin = process.env.VITE_ADVICE_API_ORIGIN;
const NO_SERVICE =
  "The build has no VITE_ADVICE_API_ORIGIN; a static build cannot enter a compute job.";

const ENTRY = 35249001;
const JOB = "advice-0123456789abcdef-1";
const QUEUED_BEHIND_TWO = {
  status: "queued",
  queue_position: 2,
  progress: null,
  workers: { busy: 3, total: 3 },
};
const QUEUED_NEXT = { ...QUEUED_BEHIND_TWO, queue_position: 0 };
const RUNNING_ONE_OF_THREE = {
  status: "running",
  queue_position: null,
  progress: { done: 1, total: 3 },
  workers: { busy: 3, total: 3 },
};

/** The service: every poll answers what the test last told the job to say. */
async function installService(page: Page, view: object): Promise<{ says: object }> {
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const job = { says: view };
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
        ? [
            200,
            {
              contract_version: "advice_job_view_v1",
              job_id: JOB,
              ...job.says,
            },
          ]
        : route.request().method() === "POST"
          ? [202, { job_id: JOB }]
          : [404, { error: { code: "NOT_COMPUTED" } }];
    await route.fulfill({
      status: status as number,
      contentType: "application/json",
      headers,
      body: JSON.stringify(body),
    });
  });
  return job;
}

/** Opens the member's page and asks for a plan nobody published; the job then says `view`. */
async function askForPlan(page: Page, language: Language, view: object) {
  await installLeagueMocks(page);
  await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
  const job = await installService(page, view);
  await page.goto(`/league/352490/members/${ENTRY}?window=3`);
  const copy = MESSAGES[language].leagueMembers;
  const settings = page.getByRole("region", { name: copy.planTitle });
  await settings.getByRole("radio", { name: /^5 / }).click();
  await settings.getByRole("radio", { name: "20", exact: true }).click();
  await expect(settings.getByRole("radio", { name: /^5 / })).toBeChecked();
  await expect(settings.getByRole("radio", { name: "20", exact: true })).toBeChecked();
  await expect(page).toHaveURL(/window=5.*top100=20/);
  await settings.getByRole("button", { name: copy.computeButton, exact: true }).click();
  return { dock: page.locator("[data-compute-dock]"), job };
}

/** The boxes of the bar, its fill and its stage in hand, read at one moment: an answer redraws. */
function parts(bar: Locator) {
  return bar.evaluate((node) =>
    [node, ...node.children].map((part) => {
      const { x, width } = part.getBoundingClientRect();
      return { x, width };
    }),
  );
}

async function noSidewaysScroll(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
}

for (const language of ["tr", "en"] as const) {
  const copy = MESSAGES[language].leagueMembers;
  const computeCopy = COMPUTE_COPY[language];

  test(`a waiting computation follows its place in line and its stages in ${language}`, async ({
    page,
  }) => {
    test.skip(!apiOrigin, NO_SERVICE);
    await page.setViewportSize({ width: 375, height: 667 });
    const { dock, job } = await askForPlan(page, language, QUEUED_BEHIND_TWO);
    const main = page.locator("main");

    await expect(dock.getByText(computeCopy.queueAhead(2), { exact: false })).toBeVisible();
    await expect(dock.getByText(computeCopy.workersBusy(3, 3), { exact: true })).toBeVisible();
    await expect(dock.getByRole("progressbar")).toHaveCount(0);
    await expect(
      main.getByText(
        copy.computeEcho(`${copy.computeEchoStates.queued}, ${computeCopy.queueAhead(2)}`),
        { exact: true },
      ),
    ).toBeVisible();

    job.says = QUEUED_NEXT;
    await expect(dock.getByText(computeCopy.queueNext, { exact: false })).toBeVisible();
    await expect(dock.getByRole("progressbar")).toHaveCount(0);

    job.says = RUNNING_ONE_OF_THREE;
    const bar = dock.getByRole("progressbar", { name: copy.computeRunning });
    await expect(bar).toHaveAttribute("aria-valuenow", "1");
    await expect(bar).toHaveAttribute("aria-valuemax", "3");
    await expect(bar).toHaveAttribute("aria-valuetext", "1/3");
    await expect(dock.getByText(copy.computeRunning, { exact: true })).toBeVisible();
    await expect(dock.getByText("1/3", { exact: false })).toBeVisible();
    await expect(dock.getByText(computeCopy.workersBusy(3, 3), { exact: true })).toBeVisible();
    await expect(dock).not.toContainText("%");
    await expect(
      main.getByText(copy.computeEcho(`${copy.computeEchoStates.running}, 1/3`), { exact: true }),
    ).toBeVisible();

    // A third of the bar is solved, and the next third is the stage in hand.
    const [track, solved, inHand] = await parts(bar);
    expect(solved!.width).toBeCloseTo(track!.width / 3, 0);
    expect(inHand!.width).toBeCloseTo(track!.width / 3, 0);
    expect(inHand!.x).toBeCloseTo(track!.x + track!.width / 3, 0);

    expect(await noSidewaysScroll(page)).toBe(true);
    expect((await dock.boundingBox())!.height).toBeLessThanOrEqual(667 * 0.45 + 1);
  });

  test(`a service that says nothing leaves the word and the bar in ${language}`, async ({
    page,
  }) => {
    test.skip(!apiOrigin, NO_SERVICE);
    const { dock, job } = await askForPlan(page, language, { status: "queued" });

    await expect(dock.getByText(copy.computeQueued, { exact: true })).toBeVisible();
    await expect(dock.getByRole("progressbar")).toHaveCount(0);

    job.says = { status: "running" };
    const bar = dock.getByRole("progressbar", { name: copy.computeRunning });
    await expect(bar).toBeVisible();
    await expect(bar).not.toHaveAttribute("aria-valuenow");
    await expect(dock).not.toContainText("/");
    await expect(
      page
        .locator("main")
        .getByText(copy.computeEcho(copy.computeEchoStates.running), { exact: true }),
    ).toBeVisible();
    const [track, solved, inHand] = await parts(bar);
    expect(solved!.width).toBe(0);
    expect(inHand!.width).toBeCloseTo(track!.width, 0);
  });
}

// The dock's bar reads over the card in both palettes; a scan takes it at rest.
for (const colorScheme of ["light", "dark"] as const) {
  test(`the waiting dock raises nothing in the ${colorScheme} palette`, async ({ page }) => {
    test.skip(!apiOrigin, NO_SERVICE);
    await page.emulateMedia({ colorScheme });
    const { dock } = await askForPlan(page, "tr", RUNNING_ONE_OF_THREE);
    await expect(dock.getByRole("progressbar")).toBeVisible();
    await atRest(page);
    const scan = await new AxeBuilder({ page }).include("[data-compute-dock]").analyze();
    expect(scan.violations).toEqual([]);
  });
}

test("each answer from the service sends one pulse, and nothing loops", async ({ page }) => {
  test.skip(!apiOrigin, NO_SERVICE);
  const { dock } = await askForPlan(page, "tr", RUNNING_ONE_OF_THREE);
  const inHand = dock.locator("[data-stage-now]");
  await expect(inHand).toBeAttached();
  // Each answer draws the stage anew, and its pulse runs once and ends.
  const first = await inHand.evaluateHandle((node) => node);
  await page.waitForFunction((node) => !node?.isConnected, first, { timeout: 7000 });
  await expect
    .poll(() =>
      inHand.evaluate((node) =>
        node
          .getAnimations({ subtree: true })
          .map((motion) => motion.effect?.getTiming().iterations),
      ),
    )
    .toEqual([1]);
});

test("under reduced motion no pulse runs, and the fill and the count stay", async ({ page }) => {
  test.skip(!apiOrigin, NO_SERVICE);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const { dock } = await askForPlan(page, "tr", RUNNING_ONE_OF_THREE);
  const inHand = dock.locator("[data-stage-now]");
  await expect(inHand).toBeAttached();
  await expect(dock).toContainText("1/3");
  const first = await inHand.evaluateHandle((node) => node);
  await page.waitForFunction((node) => !node?.isConnected, first, { timeout: 7000 });
  expect(await inHand.evaluate((node) => node.getAnimations({ subtree: true }).length)).toBe(0);
  const [track, solved] = await parts(dock.getByRole("progressbar"));
  expect(solved!.width).toBeCloseTo(track!.width / 3, 0);
});

test("under reduced motion a job with nothing to count draws no bar", async ({ page }) => {
  test.skip(!apiOrigin, NO_SERVICE);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const { dock, job } = await askForPlan(page, "tr", { status: "running" });
  await expect(
    dock.getByText(MESSAGES.tr.leagueMembers.computeRunning, { exact: true }),
  ).toBeVisible();
  await expect(dock.getByRole("progressbar")).toHaveCount(0);
  job.says = RUNNING_ONE_OF_THREE;
  await expect(dock.getByRole("progressbar")).toBeVisible();
});

test("a contrast theme keeps the bar's outline and its fill", async ({ page }) => {
  test.skip(!apiOrigin, NO_SERVICE);
  await page.emulateMedia({ forcedColors: "active" });
  const { dock } = await askForPlan(page, "tr", RUNNING_ONE_OF_THREE);
  const drawn = await dock.getByRole("progressbar").evaluate((node) => {
    const track = getComputedStyle(node);
    return {
      outline: track.borderTopStyle,
      trackInk: track.backgroundColor,
      fillInk: getComputedStyle(node.firstElementChild!).backgroundColor,
    };
  });
  expect(drawn.outline).toBe("solid");
  expect(drawn.fillInk).not.toBe(drawn.trackInk);
});
