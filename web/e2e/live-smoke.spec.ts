import { expect, test, type Response } from "@playwright/test";
import type {
  EntryAdvice,
  EntryAdviceIndex,
  EntrySquad,
  LeagueViewEnvelope,
} from "../src/features/league/types";
import { isForwarderRefusal, MARKER_HEADER } from "../src/features/league/forwarder/client";
import { MESSAGES } from "../src/i18n/messages";
import { pickMember } from "./identity";
import { figure } from "../src/lib/format";

// Documents whose 404 is absence: the league directory on a site from before it.
const OPTIONAL_DOCUMENTS = new Set(["/data/leagues.json"]);

// Normal offline smoke discovery skips this file; only the live config runs it.
test.skip(!process.env.LIVE_BASE_URL || Boolean(process.env.CI), "Manual live release check only.");

test("published league and member journey works without submitting a solve", async ({
  page,
}, testInfo) => {
  const origin = new URL(process.env.LIVE_BASE_URL!).origin;
  const errors: string[] = [];
  const consoleErrors: { text: string; url: string }[] = [];
  const absentDocuments = new Set<string>();
  // The FPL forwarder's own 404s and 503s, marked as its answers: a page reads each as no
  // document and shows nothing for it (#983 step 3, #1008), so they are not failures.
  const forwarderRefusals = new Set<string>();
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
      const { pathname } = new URL(response.url());
      if (response.status() === 404 && OPTIONAL_DOCUMENTS.has(pathname)) {
        absentDocuments.add(response.url());
        console.log(`optional document absent: ${response.url()}`);
      } else if (
        isForwarderRefusal(pathname, response.status(), response.headers()[MARKER_HEADER])
      ) {
        forwarderRefusals.add(response.url());
        console.log(`forwarder refusal ${response.status()}: ${response.url()}`);
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
  // The league's tree: the directory's first line, or the one tree of a site from before it.
  const directoryResponse = await page.request.get("/data/leagues.json");
  let tree = "league";
  if (directoryResponse.status() === 200) {
    const directory = (await directoryResponse.json()) as {
      payload: { leagues: { league_id: number; path: string }[] };
    };
    tree = directory.payload.leagues[0]!.path;
  } else expect(directoryResponse.status()).toBe(404);
  const membersResponse = await page.request.get(`/data/${tree}/members.json`);
  expect(membersResponse.status()).toBe(200);
  const members = (await membersResponse.json()) as {
    payload: {
      league_id: number;
      members: {
        member_kind: string;
        entry_id: number;
        manager_name: string | null;
        team_name: string | null;
      }[];
    };
  };
  const member = members.payload.members.find((entry) => entry.member_kind === "human");
  expect(member, "a published human member is required").toBeDefined();
  const entryId = member!.entry_id;
  // The league's number is in its own members record.
  const league = members.payload.league_id;
  const squadResponse = await page.request.get(`/data/${tree}/entries/${entryId}.json`);
  expect(squadResponse.status()).toBe(200);
  const squad = (await squadResponse.json()) as LeagueViewEnvelope<EntrySquad>;
  expect(squad.payload.source_snapshot_id).toBeTruthy();
  const indexResponse = await page.request.get(`/data/${tree}/advice/${entryId}/index.json`);
  expect(indexResponse.status()).toBe(200);
  const index = (await indexResponse.json()) as LeagueViewEnvelope<EntryAdviceIndex>;
  expect(index.payload.entry_id).toBe(entryId);
  const deviceMenu = index.payload.menu === "device";
  const published = await page.request.get(`/data/${tree}/advice/${entryId}/saf-puan/1.json`);
  expect(published.status()).toBe(deviceMenu ? 404 : 200);
  const advice = deviceMenu ? null : ((await published.json()) as LeagueViewEnvelope<EntryAdvice>);
  if (advice) {
    expect(advice.payload.starting_xi).toHaveLength(11);
    expect(advice.payload.source_snapshot_id).toBe(squad.payload.source_snapshot_id);
  }

  // Each member's own page and history page read this document; the journey opens one member's.
  for (const entry of members.payload.members.filter((row) => row.member_kind === "human")) {
    const response = await page.request.get(`/data/${tree}/history/${entry.entry_id}.json`);
    expect(response.status(), `history of ${entry.entry_id}`).toBe(200);
    const { payload } = (await response.json()) as { payload: { weeks: unknown[] } };
    expect(payload.weeks, `history of ${entry.entry_id}`).toBeDefined();
  }

  // Every league page stands behind "Sen kimsin?": the visitor says they are this member first.
  await page.goto(`/league/${league}/members`);
  await pickMember(page, { managerName: member!.manager_name, teamName: member!.team_name }, "en");
  await expect(page.locator("[data-member-picker]")).toHaveCount(0);
  await page.goto(`/league/${league}`);
  await expect(page.locator("main h1")).toBeVisible();
  // The scoreboard is the page's one table, and it stands once a week has finished.
  await expect(
    page
      .locator("main table")
      .or(page.getByText(MESSAGES.en.leagueScoreboard.noGameweek, { exact: true })),
  ).toBeVisible();
  await page.goto(`/league/${league}/members/${entryId}`);
  await expect(page).toHaveURL(new RegExp(`/league/${league}/members/${entryId}$`));
  if (advice) {
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
        figure(advice.payload.expected_own_points!, "en-GB"),
      ),
    );
  }
  // Past the week's deadline the page offers no settings, since nothing is computed for a
  // closed week. It reads the deadline from the published calendar, and so does this check.
  const calendarResponse = await page.request.get("/data/fixtures.json");
  const calendar = calendarResponse.ok()
    ? ((await calendarResponse.json()) as {
        payload: { season: string; gameweeks: { gameweek: number; deadline_utc: string }[] };
      })
    : null;
  const deadline =
    calendar?.payload.season === squad.payload.season
      ? calendar.payload.gameweeks.find((week) => week.gameweek === squad.payload.gameweek)
          ?.deadline_utc
      : undefined;
  const closed = deadline !== undefined && Date.now() >= Date.parse(deadline);
  if (closed) await expect(page.getByTestId("deadline-passed")).toBeVisible();
  if (deviceMenu && !closed) await expect(page.locator("[data-device-compute]")).toBeEnabled();
  for (const selector of [
    'input[name="strategy"][value="saf-puan"]',
    'input[name="window"][value="1"]',
    'input[name="chip"][value=""]',
  ])
    if (closed) await expect(page.locator(selector)).toHaveCount(0);
    else await expect(page.locator(selector)).toBeEnabled();
  // The Top 100 menu is offered by the compute service; with the PC backend down the page
  // has nothing to offer it from, so it is checked only when the service answered.
  if (capabilitiesUrl && !closed)
    await expect(page.locator('input[name="top100"][value="0"]')).toBeEnabled();
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
        source_snapshot_id: squad.payload.source_snapshot_id,
      });
      console.log(`backend cache hit matches published capture: ${cacheRead}`);
    }
  }
  // The member's history is linked from the page (under the squad, and by the last finished
  // week's card when the member has one) and from the sidebar, which a phone keeps in a
  // closed drawer. Any link the visitor can see lands on the same page.
  await page
    .locator(`a[href="/league/${league}/members/${entryId}/history"]`)
    .filter({ visible: true })
    .first()
    .click();
  await expect(page).toHaveURL(new RegExp(`/league/${league}/members/${entryId}/history$`));
  await expect(page.locator("main h1")).toBeVisible();
  await page.waitForLoadState("networkidle");
  const historyResponse = await page.request.get(`/data/${tree}/history/${entryId}.json`);
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
          ((absentDocuments.has(url) || cacheMissUrls.has(url)) &&
            /Failed to load resource:.*404/.test(text)) ||
          (forwarderRefusals.has(url) && /Failed to load resource:.*\b(?:404|503)\b/.test(text))
        ),
    ),
    "no console error apart from the reported optional document, validated cache miss or forwarder refusal",
  ).toEqual([]);
  expect(errors, "no browser or console error").toEqual([]);
});
