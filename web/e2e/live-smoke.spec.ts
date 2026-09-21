import { expect, test, type Response } from "@playwright/test";
import type { EntryAdvice, LeagueViewEnvelope } from "../src/features/league/types";
import { MESSAGES } from "../src/i18n/messages";
import { points } from "../src/lib/format";

// publish_series_horizon in application/weekly_suggestion_eval.py omits this
// document until the settled series supports a horizon. Only its 404 is absence.
const OPTIONAL_DOCUMENTS = new Set(["/data/league/series-horizon.json"]);

// Normal offline smoke discovery skips this file; only the live config runs it.
test.skip(!process.env.LIVE_BASE_URL || Boolean(process.env.CI), "Manual live release check only.");

test("published league and member journey works without submitting a solve", async ({
  page,
}, testInfo) => {
  const origin = new URL(process.env.LIVE_BASE_URL!).origin;
  const errors: string[] = [];
  const consoleErrors: { text: string; url: string }[] = [];
  const absentDocuments = new Set<string>();
  const cacheMissUrls = new Set<string>();
  const adviceMisses: Response[] = [];
  const failures: string[] = [];
  const writes: string[] = [];
  let capabilitiesUrl: string | undefined;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error")
      consoleErrors.push({ text: message.text(), url: message.location().url });
  });
  page.on("requestfailed", (request) => {
    if (new URL(request.url()).origin === origin) failures.push(request.url());
  });
  page.on("response", (response) => {
    if (
      response.status() === 404 &&
      response.request().method() === "GET" &&
      /^\/api\/v1\/leagues\/\d+\/entries\/\d+\/advice$/.test(new URL(response.url()).pathname)
    )
      adviceMisses.push(response);
    if (
      response.status() === 200 &&
      /^\/api\/v1\/leagues\/\d+\/capabilities$/.test(new URL(response.url()).pathname)
    )
      capabilitiesUrl = response.url();
    if (new URL(response.url()).origin === origin && response.status() >= 400) {
      if (response.status() === 404 && OPTIONAL_DOCUMENTS.has(new URL(response.url()).pathname)) {
        absentDocuments.add(response.url());
        console.log(`optional document absent: ${response.url()}`);
      } else failures.push(`${response.status()} ${response.url()}`);
    }
  });
  // Even an accidental UI submission cannot create a job during this release check.
  await page.route("**/*", (route) => {
    const request = route.request();
    if (
      new URL(request.url()).pathname.startsWith("/api/v1/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method())
    ) {
      writes.push(`${request.method()} ${request.url()}`);
      return route.abort("blockedbyclient");
    }
    return route.continue();
  });
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
  const membersResponse = await page.request.get("/data/league/members.json");
  expect(membersResponse.status()).toBe(200);
  const members = (await membersResponse.json()) as {
    payload: { league_id: number; members: { member_kind: string; entry_id: number }[] };
  };
  const member = members.payload.members.find((entry) => entry.member_kind === "human");
  expect(member, "a published human member is required").toBeDefined();
  const entryId = member!.entry_id;
  const published = await page.request.get(`/data/league/advice/${entryId}/saf-puan/1.json`);
  expect(published.status()).toBe(200);
  const advice = (await published.json()) as LeagueViewEnvelope<EntryAdvice>;
  expect(advice.payload.starting_xi).toHaveLength(11);

  const pendingDocuments = new Set([
    "/data/league/series-horizon.json",
    ...members.payload.members
      .filter((entry) => entry.member_kind === "human")
      .map((entry) => `/data/league/history/${entry.entry_id}.json`),
  ]);
  // Register before navigation; a fast table must not hide late document failures.
  const documentReads = [...pendingDocuments].map(async (path) => {
    const response = await page.waitForResponse((item) => item.url() === `${origin}${path}`, {
      timeout: 0,
    });
    if (!(OPTIONAL_DOCUMENTS.has(path) && response.status() === 404)) {
      expect(response.status(), path).toBe(200);
      expect(await response.finished(), path).toBeNull();
    }
    pendingDocuments.delete(path);
  });
  let documentTimer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      Promise.all([page.goto("/league"), ...documentReads]),
      new Promise<never>((_, reject) => {
        documentTimer = setTimeout(
          () =>
            reject(
              new Error(`League documents did not complete: ${[...pendingDocuments].join(", ")}`),
            ),
          30_000,
        );
      }),
    ]);
  } finally {
    clearTimeout(documentTimer);
  }
  await expect(page.locator("main h1")).toBeVisible();
  await expect(page.locator("main table").first()).toBeVisible();
  await page.goto("/league/members");
  await page
    .getByRole("row")
    .filter({ has: page.locator(`a[href="/league/members/${entryId}"]`) })
    .getByRole("button", { name: MESSAGES.en.leagueMembers.viewerSelect, exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`/league/members/${entryId}$`));
  const plan = page.locator('[aria-labelledby="entry-advice-title"]');
  await expect(plan).toBeVisible();
  for (const player of advice.payload.starting_xi ?? [])
    await expect(plan).toContainText(player.name);
  expect(advice.payload.captain).toBeTruthy();
  await expect(
    plan
      .locator("dl > div")
      .filter({ has: page.getByText(MESSAGES.en.leagueMembers.captainLabel, { exact: true }) }),
  ).toContainText(advice.payload.captain!.name);
  expect(Number.isFinite(advice.payload.expected_own_points)).toBe(true);
  await expect(plan).toContainText(
    MESSAGES.en.leagueMembers.expectedOwnPoints(
      points(advice.payload.expected_own_points!, 1, "en-GB"),
    ),
  );
  for (const selector of [
    'input[name="strategy"][value="saf-puan"]',
    'input[name="window"][value="1"]',
    'input[name="top100"][value="0"]',
    'input[name="chip"][value=""]',
  ])
    await expect(page.locator(selector)).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath("member.png"), fullPage: true });

  if (process.env.LIVE_SMOKE_COMPUTE === "1") {
    // GET is cache-only: NOT_COMPUTED is valid absence, never a reason to POST.
    // A published plan need not cause a page-level cache read. Use the backend
    // actually contacted by this page, never an invented endpoint or a POST.
    await expect.poll(() => capabilitiesUrl).toBeTruthy();
    const capabilities = new URL(capabilitiesUrl!);
    expect(capabilities.pathname).toBe(`/api/v1/leagues/${members.payload.league_id}/capabilities`);
    const cacheRead = new URL(
      `/api/v1/leagues/${members.payload.league_id}/entries/${entryId}/advice?strategy=saf-puan&window=1`,
      capabilities.origin,
    );
    // Use the browser's fetch so the public backend's CORS policy is exercised too.
    const cached = await page.evaluate(async (url) => {
      const response = await fetch(url);
      return { status: response.status, body: await response.json() };
    }, cacheRead.toString());
    if (cached.status === 404) {
      expect(cached.body.error?.code).toBe("NOT_COMPUTED");
      cacheMissUrls.add(cacheRead.toString());
      console.log(`backend reachable, selection not computed: ${cacheRead}`);
    } else {
      expect(cached.status).toBe(200);
      const answer = cached.body as LeagueViewEnvelope<EntryAdvice>;
      expect(answer.payload).toMatchObject({
        entry_id: entryId,
        mode: "saf-puan",
        window: 1,
        source_snapshot_id: advice.payload.source_snapshot_id,
      });
      console.log(`backend cache hit matches published capture: ${cacheRead}`);
    }
  }
  await page.locator(`a[href="/league/members/${entryId}/history"]`).click();
  await expect(page).toHaveURL(new RegExp(`/league/members/${entryId}/history$`));
  await expect(page.locator("main h1")).toBeVisible();
  await page.waitForLoadState("networkidle");
  const historyResponse = await page.request.get(`/data/league/history/${entryId}.json`);
  expect(historyResponse.status()).toBe(200);
  const history = (await historyResponse.json()) as { payload: { weeks: { gameweek: number }[] } };
  if (history.payload.weeks.length) {
    await expect(page.getByRole("combobox")).toContainText(
      MESSAGES.en.suggestionHistory.gameweek(history.payload.weeks[0]!.gameweek),
    );
    await expect(page.getByRole("table").first()).toBeVisible();
  } else {
    await expect(
      page.getByText(MESSAGES.en.suggestionHistory.emptyBody, { exact: true }),
    ).toBeVisible();
  }
  expect(writes, "no mutating API request is allowed").toEqual([]);
  // The model comparison also performs a cache-only GET. Admit only this member's
  // exact baseline settings and a typed NOT_COMPUTED response from the discovered API.
  for (const response of adviceMisses) {
    expect(capabilitiesUrl, "cache reads must use the discovered backend").toBeTruthy();
    const url = new URL(response.url());
    expect(url.origin).toBe(new URL(capabilitiesUrl!).origin);
    expect(url.pathname).toBe(
      `/api/v1/leagues/${members.payload.league_id}/entries/${entryId}/advice`,
    );
    expect(url.searchParams.get("strategy")).toBe("saf-puan");
    expect(url.searchParams.get("window")).toBe("1");
    expect([null, "current", "football"]).toContain(url.searchParams.get("model"));
    expect((await response.json()).error?.code).toBe("NOT_COMPUTED");
    cacheMissUrls.add(response.url());
  }
  expect(
    failures.filter((failure) => ![...cacheMissUrls].some((url) => failure === `404 ${url}`)),
    "the site's own requests must succeed apart from a validated cache miss",
  ).toEqual([]);
  expect(
    consoleErrors.filter(
      ({ text, url }) =>
        !(
          (absentDocuments.has(url) || cacheMissUrls.has(url)) &&
          /Failed to load resource:.*404/.test(text)
        ),
    ),
    "no console error apart from the reported optional document or validated cache miss",
  ).toEqual([]);
  expect(errors, "no browser or console error").toEqual([]);
});
