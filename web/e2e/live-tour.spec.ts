import { createServer } from "node:http";

import { expect, test as base, type Page, type Response } from "@playwright/test";

import { isForwarderRefusal, MARKER_HEADER } from "../src/features/league/forwarder/client";
import { STORY_ANCHORS } from "../src/features/league/pages/storyPlan";
import { MESSAGES, type Language } from "../src/i18n/messages";
import {
  entryAddress,
  leagueAddress,
  llmoptAddress,
  memberAddress,
  memberHistoryAddress,
  memberLiveAddress,
  memberToolAddress,
  memberVsAddress,
  membersAddress,
  MEMBER_TOOLS,
} from "../src/lib/leagueAddresses";

// This check reads the current publication only, never a historical season store.
const LIVE_SEASON = "2026-27";
const baseURL = process.env.LIVE_BASE_URL;
const READ_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

interface Publication {
  leagueId: number;
  entryId: number;
  leagueName: string | null;
  managerName: string | null;
  teamName: string | null;
  weekOpen: boolean;
}

interface Issue {
  check: "browser" | "request" | "content" | "empty-tool" | "decision" | "overflow" | "key-step";
  reason: string;
}

const test = base.extend<object, { publication: Publication }>({
  publication: [
    async ({ playwright }, provide) => {
      const request = await playwright.request.newContext({ baseURL });
      try {
        const directory = await request.get("/data/leagues.json");
        expect(directory.status(), "published league directory").toBe(200);
        const tree = (await directory.json()).payload.leagues[0]?.path as string | undefined;
        expect(tree, "a published league is required").toMatch(/^leagues\/\d+$/);
        const membersResponse = await request.get(`/data/${tree}/members.json`);
        expect(membersResponse.status(), "published member list").toBe(200);
        const members = (await membersResponse.json()).payload;
        expect(members.season, "only the named live season is read").toBe(LIVE_SEASON);
        const member = members.members.find(
          (row: { member_kind: string }) => row.member_kind === "human",
        );
        expect(Boolean(member), "a published human member is required").toBe(true);
        const squadResponse = await request.get(`/data/${tree}/entries/${member.entry_id}.json`);
        expect(squadResponse.status(), "published human squad").toBe(200);
        const squad = (await squadResponse.json()).payload;
        expect(squad.season, "only the named live season is read").toBe(LIVE_SEASON);
        const calendarResponse = await request.get("/data/fixtures.json");
        expect(calendarResponse.status(), "live calendar").toBe(200);
        const calendar = (await calendarResponse.json()).payload;
        expect(calendar.season, "calendar belongs to the named live season").toBe(LIVE_SEASON);
        const deadline = calendar.gameweeks.find(
          (week: { gameweek: number }) => week.gameweek === squad.gameweek,
        )?.deadline_utc;
        expect(Number.isFinite(Date.parse(deadline)), "published week has a deadline").toBe(true);
        await provide({
          leagueId: members.league_id,
          entryId: member.entry_id,
          leagueName: members.league_name,
          managerName: member.manager_name,
          teamName: member.team_name,
          weekOpen: Date.now() < Date.parse(deadline),
        });
      } finally {
        await request.dispose();
      }
    },
    { scope: "worker" },
  ],
});

test.skip(!baseURL || Boolean(process.env.CI), "Manual live release check only.");
test.describe.configure({ retries: 0 });

function safeAddress(raw: string): string {
  const url = new URL(raw);
  // Network logs never disclose any other entry, including a private comparison cohort.
  const path = url.pathname
    .replace(/\/(entries|entry|members|advice)\/\d+/g, "/$1/<member>")
    .replace(/\/history\/(requested\/)?\d+/g, "/history/$1<member>");
  return `${url.origin}${path}`;
}

async function fenceWrites(
  page: Page,
  origin: string,
  writes: string[],
  beacons: string[],
  telemetry: string[] = [],
) {
  await page.route("**/*", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    // Answer the record locally: this visit must never enter the usage record.
    if (url.origin === origin && url.pathname === "/api/v1/usage/events") {
      beacons.push(request.method());
      return route.fulfill({ status: 204 });
    }
    // The injected analytics script writes on a visit. Keep it blocked and reported;
    // its transport cannot be a health check in a visit-only rehearsal.
    if (url.origin === origin && url.pathname === "/cdn-cgi/rum" && request.method() === "POST") {
      telemetry.push("POST /cdn-cgi/rum");
      return route.abort("blockedbyclient");
    }
    // The guard covers all origins and paths, including future non-API submissions.
    if (!READ_METHODS.has(request.method())) {
      writes.push(`${request.method()} ${safeAddress(request.url())}`);
      return route.abort("blockedbyclient");
    }
    return route.continue();
  });
}

const PAGES = [
  { name: "league", address: (p: Publication) => leagueAddress(p.leagueId) },
  { name: "members", address: (p: Publication) => membersAddress(p.leagueId) },
  { name: "decision", address: (p: Publication) => memberAddress(p.leagueId, p.entryId) },
  ...MEMBER_TOOLS.map((tool) => ({
    name: tool,
    address: (p: Publication) => memberToolAddress(p.leagueId, p.entryId, tool),
  })),
  { name: "history", address: (p: Publication) => memberHistoryAddress(p.leagueId, p.entryId) },
  { name: "VS", address: (p: Publication) => memberVsAddress(p.leagueId, p.entryId) },
  { name: "LIVE", address: (p: Publication) => memberLiveAddress(p.leagueId, p.entryId) },
  { name: "fixtures", address: () => "/fixtures" },
  { name: "entry", address: (p: Publication) => entryAddress(p.entryId) },
  { name: "LLMOPT", address: (p: Publication) => llmoptAddress(p.leagueId, p.entryId) },
  { name: "contribute", address: () => "/contribute" },
];

async function visit(
  page: Page,
  publication: Publication,
  language: Language,
  name: string,
  address: string,
) {
  const started = Date.now();
  const origin = new URL(baseURL!).origin;
  const issues: Issue[] = [];
  const writes: string[] = [];
  const beacons: string[] = [];
  const telemetry: string[] = [];
  const journey: string[] = [];
  const pending: Promise<void>[] = [];
  const allowedAbsence = new Set<string>();
  const consoleErrors: { url: string; resource: boolean }[] = [];
  const serviceOrigins = new Set([origin]);
  const record = (line: string) => journey.push(`${Date.now() - started}ms ${line}`);
  const checkResponse = async (response: Response) => {
    const url = new URL(response.url());
    if (
      url.pathname === `/api/v1/leagues/${publication.leagueId}/capabilities` ||
      (name === "entry" &&
        url.pathname === `/api/v1/public/leagues/0/entries/${publication.entryId}/capabilities`)
    )
      serviceOrigins.add(url.origin);
    if (!serviceOrigins.has(url.origin)) return;
    record(`${response.status()} ${response.request().method()} ${safeAddress(response.url())}`);
    if (response.status() < 400) return;
    // These are typed absence, as in the smoke, never arbitrary successful responses.
    if (
      isForwarderRefusal(url.pathname, response.status(), response.headers()[MARKER_HEADER]) ||
      (response.status() === 404 &&
        url.pathname ===
          `/data/leagues/${publication.leagueId}/history/requested/${publication.entryId}.json`)
    ) {
      allowedAbsence.add(response.url());
      return;
    }
    if (
      response.status() === 404 &&
      response.request().method() === "GET" &&
      (url.pathname ===
        `/api/v1/leagues/${publication.leagueId}/entries/${publication.entryId}/advice` ||
        (name === "entry" &&
          url.pathname === `/api/v1/public/leagues/0/entries/${publication.entryId}/advice`)) &&
      url.searchParams.get("strategy") === "saf-puan" &&
      url.searchParams.get("window") === "1" &&
      [null, "current", "football"].includes(url.searchParams.get("model")) &&
      (await response.json().catch(() => null))?.error?.code === "NOT_COMPUTED"
    ) {
      allowedAbsence.add(response.url());
      return;
    }
    issues.push({
      check: "request",
      reason: `HTTP ${response.status()} ${safeAddress(response.url())}`,
    });
  };
  page.on("response", (response) => pending.push(checkResponse(response)));
  page.on("pageerror", (error) =>
    issues.push({ check: "browser", reason: `page error: ${error.name}` }),
  );
  page.on("console", (message) => {
    if (message.type() === "error")
      consoleErrors.push({
        url: message.location().url,
        resource: /^Failed to load resource:/.test(message.text()),
      });
  });
  page.on("requestfailed", (request) => {
    const url = new URL(request.url());
    if (
      url.origin === origin &&
      url.pathname === "/cdn-cgi/rum" &&
      request.method() === "POST" &&
      request.failure()?.errorText.startsWith("net::ERR_BLOCKED_BY_CLIENT")
    ) {
      allowedAbsence.add(request.url());
      return;
    }
    if (new URL(request.url()).origin === origin)
      issues.push({
        check: "request",
        reason: `${request.failure()?.errorText} ${safeAddress(request.url())}`,
      });
  });
  await fenceWrites(page, origin, writes, beacons, telemetry);
  await page.addInitScript(
    ({ publication, language }) => {
      localStorage.setItem("squadopt.language", language);
      localStorage.setItem("squadopt.league", String(publication.leagueId));
      // The claim lives in this tab only; it is never submitted to a service.
      sessionStorage.setItem("squadopt.member", JSON.stringify(publication));
    },
    { publication, language },
  );
  try {
    await page.goto(address, { waitUntil: "load" });
    await expect(page.locator("main")).toBeVisible();
    await expect(page.locator("main")).not.toHaveText("");
    await page.waitForLoadState("networkidle", { timeout: 15_000 });
    await page.evaluate(() => document.fonts.ready);
    const main = page.locator("main");
    const text = (await main.innerText()).trim();
    const loading = [MESSAGES[language].common.loading, MESSAGES[language].leagueMembers.loading];
    if (!text || loading.includes(text))
      issues.push({ check: "content", reason: "main region has no settled page content" });
    if (await page.locator("[data-member-picker]").count())
      issues.push({ check: "content", reason: "member gate hid the requested page" });
    if (
      publication.weekOpen &&
      (text.includes(MESSAGES[language].leagueMembers.toolEmpty) ||
        /\btoolEmpty\b|Nothing here for this week/.test(text))
    )
      issues.push({ check: "empty-tool", reason: "open week renders the empty-tool message" });
    if ((name === "decision" || name === "entry") && publication.weekOpen) {
      const panel = page.locator('[data-mark="decision"]');
      const planOrCompute = panel
        .locator(
          `#${STORY_ANCHORS.captain}, [data-decision-compute] button, [data-device-compute], [data-compute]`,
        )
        .filter({ visible: true });
      if ((await panel.count()) === 0 || (await planOrCompute.count()) === 0)
        issues.push({
          check: "decision",
          reason: "decision panel has neither a plan nor a compute button",
        });
    }
    if (name === "LLMOPT") {
      const key = page.locator('[data-zone="llmopt-model"] input[id$="-key"]');
      if ((await key.count()) !== 1 || (await key.inputValue()) !== "")
        issues.push({ check: "key-step", reason: "LLMOPT did not reach the empty key step" });
    }
    const width = await page.evaluate(() => ({
      viewport: window.innerWidth,
      content: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    }));
    if (width.content > width.viewport + 1)
      issues.push({
        check: "overflow",
        reason: `horizontal overflow: ${width.content}px > ${width.viewport}px`,
      });
  } catch (error) {
    issues.push({
      check: "content",
      reason: `page did not settle (${error instanceof Error ? error.name : "unknown error"})`,
    });
  }
  await Promise.all(pending);
  for (const error of consoleErrors)
    if (!(error.resource && allowedAbsence.has(error.url)))
      issues.push({
        check: "browser",
        reason: `console error${error.url ? ` at ${safeAddress(error.url)}` : ""}`,
      });
  const viewport = page.viewportSize();
  const label = `${name} ${new URL(address, baseURL).href} ${language} ${viewport?.width}x${viewport?.height}`;
  for (const issue of issues) record(`FAIL ${label}: ${issue.check}: ${issue.reason}`);
  record(
    `SUMMARY ${label}: ${Date.now() - started}ms, ${beacons.length} local beacons, ${telemetry.length} blocked analytics writes (transport omitted), ${writes.length} blocked service writes, ${issues.length} issues`,
  );
  console.log(journey.filter((line) => /FAIL |SUMMARY /.test(line)).join("\n"));
  // Detach before context disposal cancels its remaining reads.
  page.removeAllListeners("requestfailed");
  page.removeAllListeners("response");
  page.removeAllListeners("console");
  page.removeAllListeners("pageerror");
  return { issues, writes, journey };
}

test("read-only fence answers beacons and blocks every other write", async ({ page }) => {
  const received: string[] = [];
  const server = createServer((request, response) => {
    received.push(`${request.method} ${request.url}`);
    response.setHeader("Content-Type", "text/html");
    response.end("<!doctype html><title>Read-only fence</title>");
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("No local fence listener");
    const origin = `http://127.0.0.1:${address.port}`;
    const writes: string[] = [];
    const beacons: string[] = [];
    await fenceWrites(page, origin, writes, beacons);
    await page.goto(origin);
    const status = await page.evaluate(async () => {
      const read = await fetch("/read");
      const beacon = await fetch("/api/v1/usage/events", { method: "POST", body: "{}" });
      navigator.sendBeacon("/api/v1/usage/events", "{}");
      const solve = await fetch("/api/v1/solve", { method: "POST" }).catch(() => null);
      const other = await fetch("/outside-api", { method: "PUT" }).catch(() => null);
      return { read: read.status, beacon: beacon.status, solve, other };
    });
    await expect.poll(() => beacons.length).toBe(2);
    expect(status).toEqual({ read: 200, beacon: 204, solve: null, other: null });
    expect(writes).toHaveLength(2);
    expect(received).toEqual(["GET /", "GET /read"]);
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
});

for (const target of PAGES) {
  test(`${target.name}: published page has content without service writes`, async ({
    page,
    publication,
  }, testInfo) => {
    const language = testInfo.project.metadata.language as Language;
    const result = await visit(
      page,
      publication,
      language,
      target.name,
      target.address(publication),
    );
    // Do not let the runner attach an unredacted DOM snapshot on a later assertion.
    await page.close();
    await testInfo.attach("journey.txt", {
      body: result.journey.join("\n"),
      contentType: "text/plain",
    });
    expect(result.writes, "no mutating request may leave the browser").toEqual([]);
    expect(result.issues, `${target.name}: page health`).toEqual([]);
  });
}

// The four pages repaired in the live publication also retain ordinary open-week
// regression checks. Their symptoms are never filtered from the general page checks.
for (const target of PAGES.filter(({ name }) =>
  ["decision", "entry", "what-if", "card"].includes(name),
)) {
  test(`${target.name}: repaired open-week content is available`, async ({
    page,
    publication,
  }, testInfo) => {
    test.skip(!publication.weekOpen, "An empty open-week plan is not a closed-week fault.");
    const result = await visit(
      page,
      publication,
      testInfo.project.metadata.language as Language,
      target.name,
      target.address(publication),
    );
    await page.close();
    await testInfo.attach("journey.txt", {
      body: result.journey.join("\n"),
      contentType: "text/plain",
    });
    expect(result.writes, "no mutating request may leave the browser").toEqual([]);
    expect(result.issues, `${target.name}: repaired open-week content`).toEqual([]);
  });
}
