import { expect, test } from "@playwright/test";
import type { EntryAdvice, LeagueViewEnvelope } from "../src/features/league/types";
import { MESSAGES } from "../src/i18n/messages";

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
  const failures: string[] = [];
  const writes: string[] = [];
  let cacheRead: string | undefined;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error")
      consoleErrors.push({ text: message.text(), url: message.location().url });
  });
  page.on("requestfailed", (request) => {
    if (new URL(request.url()).origin === origin) failures.push(request.url());
  });
  page.on("response", (response) => {
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
    if (
      request.method() === "GET" &&
      /\/api\/v1\/leagues\/\d+\/entries\/\d+\/advice\?/.test(request.url())
    ) {
      cacheRead = request.url();
    }
    return route.continue();
  });
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
  const membersResponse = await page.request.get("/data/league/members.json");
  expect(membersResponse.status()).toBe(200);
  const members = (await membersResponse.json()) as {
    payload: { members: { member_kind: string; entry_id: number }[] };
  };
  const member = members.payload.members.find((entry) => entry.member_kind === "human");
  expect(member, "a published human member is required").toBeDefined();
  const entryId = member!.entry_id;
  const published = await page.request.get(`/data/league/advice/${entryId}/saf-puan/1.json`);
  expect(published.status()).toBe(200);
  const advice = (await published.json()) as LeagueViewEnvelope<EntryAdvice>;
  expect(advice.payload.starting_xi).toHaveLength(11);

  await page.goto("/league");
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
  for (const selector of [
    'input[name="strategy"][value="saf-puan"]',
    'input[name="window"][value="1"]',
    'input[name="top100"][value="0"]',
    'input[name="chip"][value=""]',
  ])
    await expect(page.locator(selector)).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath("member.png"), fullPage: true });

  if (process.env.LIVE_SMOKE_COMPUTE === "1") {
    // GET is cache-only by contract. A miss fails this check; it never falls back to POST.
    await expect.poll(() => cacheRead).toBeTruthy();
    const cached = await page.request.get(cacheRead!);
    expect(cached.status(), "published selection must already be in the backend cache").toBe(200);
    const answer = (await cached.json()) as LeagueViewEnvelope<EntryAdvice>;
    expect(answer.payload).toMatchObject({
      entry_id: entryId,
      mode: "saf-puan",
      window: 1,
      source_snapshot_id: advice.payload.source_snapshot_id,
    });
  }
  await page.locator(`a[href="/league/members/${entryId}/history"]`).click();
  await expect(page).toHaveURL(new RegExp(`/league/members/${entryId}/history$`));
  await expect(page.locator("main h1")).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(writes, "no mutating API request is allowed").toEqual([]);
  expect(failures, "the site's own requests must succeed").toEqual([]);
  expect(
    consoleErrors.filter(
      ({ text, url }) => !(absentDocuments.has(url) && /Failed to load resource:.*404/.test(text)),
    ),
    "no console error apart from the reported optional 404",
  ).toEqual([]);
  expect(errors, "no browser or console error").toEqual([]);
});
