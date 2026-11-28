import { createServer } from "node:http";

import { expect, test, type Page, type Request, type Response } from "@playwright/test";
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

// What the browser asked for and what came back, in order, with the time since the attempt
// began. Printed when an attempt fails, kept with the attempt's results either way.
let journey: string[] = [];
let journeyStart = 0;

function logJourney(line: string) {
  journey.push(`${String(Date.now() - journeyStart).padStart(6)}ms ${line}`);
}

interface WriteFence {
  writes: string[];
  analytics: Map<string, number>;
  beacons: number;
}

interface ConsoleError {
  text: string;
  url: string;
}

interface BackendDiagnostics {
  reads: Set<string>;
  failures: string[];
}

const READ_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
let liveMetrics: { fence: WriteFence; visits: number } | null = null;

function isBackendRead(request: Request): boolean {
  return (
    READ_METHODS.has(request.method()) && new URL(request.url()).pathname.startsWith("/api/v1/")
  );
}

function watchBackendReads(page: Page): BackendDiagnostics {
  const state: BackendDiagnostics = { reads: new Set(), failures: [] };
  page.on("request", (request) => {
    if (isBackendRead(request)) state.reads.add(request.url());
  });
  page.on("requestfailed", (request) => {
    if (isBackendRead(request)) state.failures.push(`transport ${safeAddress(request.url())}`);
  });
  page.on("response", (response) => {
    if (isBackendRead(response.request()) && response.status() >= 400)
      state.failures.push(`HTTP ${response.status()} ${safeAddress(response.url())}`);
  });
  return state;
}

function isBackendResourceError(error: ConsoleError, backend: BackendDiagnostics): boolean {
  return backend.reads.has(error.url) && /^Failed to load resource:/.test(error.text);
}

function safeAddress(raw: string): string {
  const url = new URL(raw);
  return `${url.origin}${url.pathname
    .replace(/\/(entries|entry|members|advice)\/\d+/g, "/$1/<member>")
    .replace(/\/history\/(requested\/)?\d+/g, "/history/$1<member>")}`;
}

async function liveFailure(page: Page, stage: string): Promise<Error> {
  const address = safeAddress(page.url());
  if (!page.isClosed()) await page.close();
  return new Error(`Live smoke failed at ${address} during ${stage}`);
}

async function installWriteFence(page: Page, origin: string): Promise<WriteFence> {
  const state: WriteFence = { writes: [], analytics: new Map(), beacons: 0 };
  await page.route("**/*", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === origin && url.pathname === "/api/v1/usage/events") {
      state.beacons += 1;
      return route.fulfill({ status: 204 });
    }
    if (url.origin === origin && url.pathname === "/cdn-cgi/rum" && request.method() === "POST") {
      state.analytics.set(request.url(), (state.analytics.get(request.url()) ?? 0) + 1);
      return route.abort("blockedbyclient");
    }
    if (!READ_METHODS.has(request.method())) {
      state.writes.push(`${request.method()} ${safeAddress(request.url())}`);
      return route.abort("blockedbyclient");
    }
    return route.continue();
  });
  return state;
}

function isBlockedAnalytics(request: Request, origin: string, fence: WriteFence): boolean {
  const url = new URL(request.url());
  return (
    url.origin === origin &&
    url.pathname === "/cdn-cgi/rum" &&
    request.method() === "POST" &&
    fence.analytics.has(request.url()) &&
    request.failure()?.errorText.startsWith("net::ERR_BLOCKED_BY_CLIENT") === true
  );
}

function withoutBlockedAnalyticsConsole(
  errors: ConsoleError[],
  origin: string,
  fence: WriteFence,
): ConsoleError[] {
  // At most one native error per blocked POST. A GET or any other error at the same
  // address cannot be hidden by a URL-wide exception.
  const remaining = new Map(fence.analytics);
  return errors.filter(({ text, url: raw }) => {
    if (!/^Failed to load resource:.*net::ERR_BLOCKED_BY_CLIENT(?:[.\s]|$)/.test(text)) return true;
    const count = remaining.get(raw) ?? 0;
    if (count === 0) return true;
    const url = new URL(raw);
    if (url.origin !== origin || url.pathname !== "/cdn-cgi/rum") return true;
    remaining.set(raw, count - 1);
    return false;
  });
}

test.afterEach(async ({ page }, testInfo) => {
  const address = safeAddress(page.url());
  // Closing before the reporter runs prevents a failed assertion from retaining a
  // live DOM snapshot. Report the redacted journey instead of response bodies.
  if (!page.isClosed()) await page.close();
  if (liveMetrics) {
    const summary = {
      profile: testInfo.project.name,
      visits: liveMetrics.visits,
      local_beacons: liveMetrics.fence.beacons,
      blocked_analytics: [...liveMetrics.fence.analytics.values()].reduce((sum, n) => sum + n, 0),
      blocked_service_writes: liveMetrics.fence.writes.length,
      elapsed_ms: Date.now() - journeyStart,
    };
    console.log(`LIVE_SMOKE_SUMMARY ${JSON.stringify(summary)}`);
    await testInfo.attach("safety-summary.json", {
      body: JSON.stringify(summary),
      contentType: "application/json",
    });
  }
  const log = journey.join("\n");
  await testInfo.attach("journey.txt", { body: log, contentType: "text/plain" });
  if (testInfo.status === testInfo.expectedStatus) return;
  console.log(
    `LIVE SMOKE ATTEMPT ${testInfo.retry + 1} FAILED (${testInfo.project.name}) at ${address}\n` +
      `journey of this attempt:\n${log}`,
  );
});

test("smoke write fence blocks analytics and all other writes on every origin", async ({
  page,
}) => {
  journey = [];
  journeyStart = Date.now();
  liveMetrics = null;
  let receivedWrites = 0;
  const servers = [0, 1].map(() =>
    createServer((request, response) => {
      if (!READ_METHODS.has(request.method ?? "")) receivedWrites += 1;
      response.setHeader("Access-Control-Allow-Origin", "*");
      response.setHeader("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS, POST, PUT");
      if (request.url === "/api/v1/new-backend-route") response.statusCode = 404;
      if (request.url === "/api/v1/unavailable") response.statusCode = 503;
      response.end("<!doctype html><title>Local smoke fence</title>");
    }),
  );
  await Promise.all(
    servers.map((server) => new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve))),
  );
  try {
    const origins = servers.map((server) => {
      const address = server.address();
      if (!address || typeof address === "string") throw new Error("No local fence listener");
      return `http://127.0.0.1:${address.port}`;
    });
    const origin = origins[0]!;
    const fence = await installWriteFence(page, origin);
    const backend = watchBackendReads(page);
    const failures: { method: string; analytics: boolean; url: string; error: string }[] = [];
    page.on("requestfailed", (request) =>
      failures.push({
        method: request.method(),
        analytics: isBlockedAnalytics(request, origin, fence),
        url: request.url(),
        error: request.failure()?.errorText ?? "",
      }),
    );
    await page.route(`${origin}/cdn-cgi/rum`, (route) =>
      route.request().method() === "GET" ? route.abort("blockedbyclient") : route.fallback(),
    );
    await page.goto(origin);
    const result = await page.evaluate(async (otherOrigin) => {
      const read = await fetch("/read");
      const usage = await fetch("/api/v1/usage/events", { method: "POST", body: "{}" });
      const backendStatuses = await Promise.all(
        ["/api/v1/new-backend-route", "/api/v1/unavailable"].map(
          async (url) => (await fetch(url)).status,
        ),
      );
      navigator.sendBeacon("/api/v1/usage/events", "{}");
      const solve = await fetch("/api/v1/solve", { method: "POST" }).catch(() => null);
      const outside = await fetch("/outside-api", { method: "POST" }).catch(() => null);
      const foreign = await fetch(`${otherOrigin}/outside-api`, { method: "PUT" }).catch(
        () => null,
      );
      await fetch("/cdn-cgi/rum", { method: "POST", body: "{}" }).catch(() => null);
      await fetch("/cdn-cgi/rum").catch(() => null);
      return { read: read.status, usage: usage.status, backendStatuses, solve, outside, foreign };
    }, origins[1]!);
    const targetFailures = () =>
      failures.filter((failure) => new URL(failure.url).pathname !== "/api/v1/usage/events");
    await expect.poll(() => targetFailures().length).toBe(5);
    await expect.poll(() => fence.beacons).toBe(2);
    await page.goto(`${origin}/entry/2199732?private=not-logged`);
    let syntheticFailure: Error | undefined;
    try {
      throw await liveFailure(page, "synthetic guard phase");
    } catch (error) {
      syntheticFailure = error as Error;
    }
    expect(page.isClosed()).toBe(true);
    expect(syntheticFailure?.message).toBe(
      `Live smoke failed at ${origin}/entry/<member> during synthetic guard phase`,
    );
    expect(result).toEqual({
      read: 200,
      usage: 204,
      backendStatuses: [404, 503],
      solve: null,
      outside: null,
      foreign: null,
    });
    expect(backend.failures).toHaveLength(2);
    const backendError = {
      text: "Failed to load resource: the server responded with a status of 503",
      url: `${origin}/api/v1/unavailable`,
    };
    expect(isBackendResourceError(backendError, backend)).toBe(true);
    expect(
      isBackendResourceError({ ...backendError, url: `${origin}/assets/missing.js` }, backend),
    ).toBe(false);
    expect(fence.writes).toHaveLength(3);
    expect(failures.filter((failure) => failure.analytics)).toHaveLength(1);
    expect(
      failures.filter(
        (failure) =>
          failure.method === "GET" && failure.url.endsWith("/cdn-cgi/rum") && !failure.analytics,
      ),
    ).toHaveLength(1);
    expect(receivedWrites).toBe(0);
    // Chromium can cancel a sendBeacon after its locally fulfilled 204. It must
    // still have been answered in the browser and must not reach either server.
    expect(
      failures
        .filter((failure) => new URL(failure.url).pathname === "/api/v1/usage/events")
        .every((failure) => failure.method === "POST" && failure.error === "net::ERR_ABORTED"),
    ).toBe(true);
    const rumError = {
      text: "Failed to load resource: net::ERR_BLOCKED_BY_CLIENT",
      url: `${origin}/cdn-cgi/rum`,
    };
    expect(withoutBlockedAnalyticsConsole([rumError, rumError], origin, fence)).toHaveLength(1);
    const otherError = {
      ...rumError,
      text: "Failed to load resource: the server responded with a status of 500",
    };
    expect(withoutBlockedAnalyticsConsole([otherError], origin, fence)).toEqual([otherError]);
  } finally {
    if (!page.isClosed()) await page.close();
    await Promise.all(
      servers.map(
        (server) =>
          new Promise<void>((resolve, reject) =>
            server.close((error) => (error ? reject(error) : resolve())),
          ),
      ),
    );
  }
});

test("published league and member journey works without submitting a solve", async ({
  page,
}, testInfo) => {
  journey = [];
  journeyStart = Date.now();
  liveMetrics = null;
  if (testInfo.retry > 0)
    console.log(
      `LIVE SMOKE RETRY ${testInfo.retry} (${testInfo.project.name}): the attempt before this one failed, see its journey above`,
    );
  const origin = new URL(process.env.LIVE_BASE_URL!).origin;
  const errors: string[] = [];
  const consoleErrors: ConsoleError[] = [];
  const optionalDocuments = new Set(OPTIONAL_DOCUMENTS);
  const absentDocuments = new Set<string>();
  // The FPL forwarder's own 404s and 503s, marked as its answers: a page reads each as no
  // document and shows nothing for it (#983 step 3, #1008), so they are not failures.
  const forwarderRefusals = new Set<string>();
  const cacheMissUrls = new Set<string>();
  const adviceMisses: Response[] = [];
  const failures: string[] = [];
  const fence = await installWriteFence(page, origin);
  const backend = watchBackendReads(page);
  const writes = fence.writes;
  liveMetrics = { fence, visits: 0 };
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame() && new URL(frame.url()).origin === origin)
      liveMetrics!.visits += 1;
  });
  let stage = "discovering published documents";
  try {
    const staticPlanReads: string[] = [];
    let capabilitiesUrl: string | undefined;
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (
        url.origin === origin &&
        /^\/data\/(?:leagues\/\d+|league)\/advice\/\d+\/[^/]+\/\d+\.json$/.test(url.pathname)
      )
        staticPlanReads.push(request.url());
    });
    page.on("pageerror", (error) => errors.push(error.name));
    page.on("console", (message) => {
      if (message.type() === "error")
        consoleErrors.push({ text: message.text(), url: message.location().url });
    });
    page.on("requestfailed", (request) => {
      if (isBackendRead(request)) {
        logJourney(`BACKEND transport ${safeAddress(request.url())} (not gated)`);
        return;
      }
      if (isBlockedAnalytics(request, origin, fence)) {
        logJourney(`BLOCKED ANALYTICS POST ${safeAddress(request.url())}`);
        return;
      }
      logJourney(
        `FAILED ${request.failure()?.errorText} ${request.method()} ${safeAddress(request.url())}`,
      );
      const url = new URL(request.url());
      // Leaving a member cancels its polling, its device-input prefetch and, when the edge is
      // slow enough that it is still on its way, the history document the next page reads again
      // (with every response 300 ms later this failed both profiles, 9 Nov). Other failures
      // stay red.
      const cancelledRead =
        request.method() === "GET" &&
        request.failure()?.errorText === "net::ERR_ABORTED" &&
        (/^\/api\/v1\/fpl\/live\/\d+$/.test(url.pathname) ||
          /^\/data\/device\/[^/]+\/device-plan\.json$/.test(url.pathname) ||
          /^\/data\/(?:leagues\/\d+|league)\/history\/(?:requested\/)?\d+\.json$/.test(
            url.pathname,
          ));
      if (url.origin === origin && cancelledRead)
        console.log(`read cancelled by leaving its page: ${safeAddress(request.url())}`);
      // A usage beacon may be cut off by the page it left; the record never holds a release back.
      const usageBeacon = url.pathname === "/api/v1/usage/events";
      if (url.origin === origin && !cancelledRead && !usageBeacon)
        failures.push(`${request.failure()?.errorText} ${request.url()}`);
    });
    page.on("response", (response) => {
      logJourney(
        `${response.status()} ${response.request().method()} ${safeAddress(response.url())}`,
      );
      // The release moves the backend only after this site gate. Its old routes
      // and transient failures must not decide whether the new site is published.
      if (isBackendRead(response.request()) && process.env.LIVE_SMOKE_COMPUTE !== "1") return;
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
        if (response.status() === 404 && optionalDocuments.has(pathname)) {
          absentDocuments.add(response.url());
          console.log(`optional document absent: ${safeAddress(response.url())}`);
        } else if (
          isForwarderRefusal(pathname, response.status(), response.headers()[MARKER_HEADER])
        ) {
          forwarderRefusals.add(response.url());
          console.log(`forwarder refusal ${response.status()}: ${safeAddress(response.url())}`);
        } else failures.push(`${response.status()} ${response.url()}`);
      }
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
    // A week published before requested-history export has no such document yet.
    optionalDocuments.add(`/data/${tree}/history/requested/${entryId}.json`);
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
    // Pages can retain deleted URLs at older edges. Probe this publication's cache key;
    // the browser journey below must also prove a device menu never reads those old plans.
    const published = await page.request.get(
      `/data/${tree}/advice/${entryId}/saf-puan/1.json?v=${encodeURIComponent(index.generated_at_utc)}`,
    );
    expect(published.status()).toBe(deviceMenu ? 404 : 200);
    const advice = deviceMenu
      ? null
      : ((await published.json()) as LeagueViewEnvelope<EntryAdvice>);
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
    stage = "member selection and league page checks";
    await page.goto(`/league/${league}/members`);
    await pickMember(
      page,
      { managerName: member!.manager_name, teamName: member!.team_name },
      "en",
    );
    await expect(page.locator("[data-member-picker]")).toHaveCount(0);
    await page.goto(`/league/${league}`);
    await expect(page.locator("main h1")).toBeVisible();
    // The scoreboard is the page's one table, and it stands once a week has finished.
    await expect(
      page
        .locator("main table")
        .or(page.getByText(MESSAGES.en.leagueScoreboard.noGameweek, { exact: true })),
    ).toBeVisible();
    stage = "member decision page checks";
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
    if (process.env.LIVE_SMOKE_COMPUTE === "1" && capabilitiesUrl && !closed)
      await expect(page.locator('input[name="top100"][value="0"]')).toBeEnabled();

    if (process.env.LIVE_SMOKE_COMPUTE === "1") {
      stage = "cache-only backend checks";
      // GET is cache-only: NOT_COMPUTED is valid absence, never a reason to POST.
      // A published plan need not cause a page-level cache read. Use the backend
      // actually contacted by this page, never an invented endpoint or a POST.
      await expect.poll(() => capabilitiesUrl).toBeTruthy();
      const capabilities = new URL(capabilitiesUrl!);
      expect(capabilities.pathname).toBe(
        `/api/v1/leagues/${members.payload.league_id}/capabilities`,
      );
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
        console.log(
          `backend reachable, selection not computed: ${safeAddress(cacheRead.toString())}`,
        );
      } else {
        expect(cached.status).toBe(200);
        const answer = cached.body as LeagueViewEnvelope<EntryAdvice>;
        expect(answer.payload).toMatchObject({
          entry_id: entryId,
          mode: "saf-puan",
          window: 1,
          source_snapshot_id: squad.payload.source_snapshot_id,
        });
        console.log(
          `backend cache hit matches published capture: ${safeAddress(cacheRead.toString())}`,
        );
      }
    }
    // The member's history is linked from the page (under the squad, and by the last finished
    // week's card when the member has one) and from the sidebar, which a phone keeps in a
    // closed drawer. Any link the visitor can see lands on the same page.
    stage = "member history page checks";
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
    const history = (await historyResponse.json()) as {
      payload: { weeks: { gameweek: number }[] };
    };
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
    stage = "write and published-plan safety checks";
    expect(writes, "no mutating request is allowed on any origin or path").toEqual([]);
    if (deviceMenu)
      expect(
        staticPlanReads.map(safeAddress),
        "a device menu must not read old published plans",
      ).toEqual([]);
    // The model comparison also performs a cache-only GET. Admit only this member's
    // exact baseline settings and a typed NOT_COMPUTED response from the discovered API.
    stage = "typed cache-miss validation";
    for (const response of process.env.LIVE_SMOKE_COMPUTE === "1" ? adviceMisses : []) {
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
    await page.close();
    stage = "request health checks";
    expect(
      failures
        .filter((failure) => ![...cacheMissUrls].some((url) => failure === `404 ${url}`))
        .map((failure) => failure.replace(/https?:\/\/\S+/g, safeAddress)),
      "the site's own requests must succeed apart from a validated cache miss",
    ).toEqual([]);
    stage = "console health checks";
    expect(
      withoutBlockedAnalyticsConsole(consoleErrors, origin, fence)
        .filter(
          ({ text, url }) =>
            !(
              ((absentDocuments.has(url) || cacheMissUrls.has(url)) &&
                /Failed to load resource:.*404/.test(text)) ||
              (process.env.LIVE_SMOKE_COMPUTE !== "1" &&
                isBackendResourceError({ text, url }, backend)) ||
              (forwarderRefusals.has(url) && /Failed to load resource:.*\b(?:404|503)\b/.test(text))
            ),
        )
        .map(({ url }) => `console error at ${url ? safeAddress(url) : "unknown script"}`),
      "no console error apart from blocked analytics, optional absence, validated cache miss or forwarder refusal",
    ).toEqual([]);
    stage = "runtime health checks";
    expect(errors, "no browser or console error").toEqual([]);
    logJourney(`BACKEND SUMMARY ${backend.failures.length} diagnostics (not gated)`);
  } catch {
    // Assertion messages can contain live DOM or response data. Keep only the
    // address and stage, close first, and let the failure still fail the test.
    throw await liveFailure(page, stage);
  }
});
