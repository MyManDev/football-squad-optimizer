import { expect, test, type Page, type Route } from "@playwright/test";
import fixture from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { installLeagueMocks } from "./leagueMocks";
import { EXAMPLE_CLAIM } from "./identity";
import { MESSAGES } from "../src/i18n/messages";
import { LLMOPT_COPY } from "../src/features/league/llmopt/copy";
import { holdModel, routeChat } from "./llmoptChat";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const ENTRY = EXAMPLE_CLAIM.entryId;
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, idempotency-key",
};
const answer = (route: Route, json: unknown, status = 200) =>
  route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: CORS })
    : route.fulfill({ status, json, headers: CORS });

async function serveDeviceMember(page: Page) {
  const original = mockEntrySquadEnvelopes[ENTRY]!;
  const block = fixture.members[0]!.entry;
  const table = {
    ...fixture.document,
    league_id: LEAGUE,
    season: original.payload.season,
    gameweek: original.payload.gameweek,
    source_snapshot_id: original.payload.source_snapshot_id!,
  };
  const byId = new Map(table.players.map((p) => [p.id, p]));
  const held = block.held.map((id) => byId.get(id)!);
  const chosen = [
    ...held.filter((p) => p.position === "GK").slice(0, 1),
    ...held.filter((p) => p.position === "DEF").slice(0, 3),
    ...held.filter((p) => p.position === "MID").slice(0, 4),
    ...held.filter((p) => p.position === "FWD").slice(0, 3),
  ];
  const starters = new Set(chosen.map((p) => p.id));
  const captain = chosen.find((p) => p.position === "MID")!.id;
  const row = (p: (typeof held)[number]) => ({
    ...original.payload.starting_xi[0]!,
    player_id: p.id,
    name: p.name,
    short_name: p.short_name,
    team: p.team,
    position: p.position,
    expected_points: p.expected_points,
    is_captain: p.id === captain,
    is_vice_captain: false,
  });
  const squad = {
    ...original,
    payload: {
      ...original.payload,
      device_plan: block,
      bank_tenths: block.bank_tenths,
      free_transfers: block.free_transfers,
      starting_xi: chosen.map(row),
      bench: held.filter((p) => !starters.has(p.id)).map(row),
    },
  };
  await page.route(`**/data/league/entries/${ENTRY}.json*`, (route) =>
    route.fulfill({ json: squad }),
  );
  await page.route("**/data/league/device-plan.json*", (route) =>
    route.fulfill({
      json: {
        contract_version: "provisional_league_ui_v1",
        generated_at_utc: original.generated_at_utc,
        source_kind: "example",
        payload: table,
      },
    }),
  );
  return { table, block, byId };
}

for (const language of ["en", "tr"] as const)
  for (const width of [1280, 375]) {
    const cases = [
      { priority: false, mode: "enabled" },
      { priority: true, mode: "enabled" },
      ...(language === "en" && width === 1280
        ? [
            { priority: false, mode: "disabled" },
            { priority: false, mode: "unavailable" },
            { priority: false, mode: "stale-off" },
            { priority: false, mode: "stale-on" },
          ]
        : []),
    ];
    for (const { priority, mode } of cases)
      test(`device ${priority ? "priorities" : "choices"} with ${mode} release control (${language}, ${width})`, async ({
        page,
      }) => {
        test.skip(!API, "API build required for the interpretation boundary.");
        await installLeagueMocks(page);
        await page.setViewportSize({ width, height: 900 });
        await page.addInitScript(
          (lang) => localStorage.setItem("squadopt.language", lang),
          language,
        );
        const { table, block, byId } = await serveDeviceMember(page);
        let release = mode;
        let workers = 0;
        page.on("worker", () => workers++);
        await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
          release === "unavailable"
            ? route.abort()
            : answer(route, {
                contract_version: "league_capabilities_v1",
                ...(release === "enabled" || release === "stale-on" ? { llmopt_vnext: true } : {}),
                league_id: LEAGUE,
                capture_snapshot_id: release.startsWith("stale-")
                  ? "previous-capture"
                  : table.source_snapshot_id,
                season: table.season,
                gameweek: table.gameweek,
                strategies: { "saf-puan": { requires_rival: false, windows: [1] } },
                preferences: { available: true },
                top100: { available: false, weights: [] },
                managers_word: { available: false },
              }),
        );
        let jobs = 0;
        await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
          if (route.request().method() === "POST") {
            jobs++;
            if (release === "disabled")
              expect(route.request().postDataJSON()).not.toHaveProperty("run");
          }
          return route.abort();
        });
        await page.route(`${API}/api/v1/contributions/players`, (route) =>
          answer(route, {
            season: table.season,
            players: table.players.map((p) => ({ id: p.id, name: p.name, team: p.team })),
          }),
        );
        await routeChat(page, API!, (route) =>
          answer(route, {
            status: "draft",
            draft: {
              hard: [{ kind: "keep_player", player_id: block.held[0] }],
              soft: priority
                ? [
                    { kind: "avoid_player", player_id: block.held[1], priority: 1 },
                    { kind: "keep_player", player_id: block.held[2], priority: 2 },
                    { kind: "keep_player", player_id: block.held[3], priority: 3 },
                  ]
                : [],
              window: 1,
              ...(priority ? { max_total_cost_tenths: 15 } : {}),
            },
          }),
        );
        await page.goto(`/league/${LEAGUE}/members/${ENTRY}/llmopt`);
        await holdModel(page);
        await page
          .getByRole("textbox", {
            name: language === "tr" ? "Plan talimatların" : "Plan instructions",
          })
          .fill("Keep this player.");
        await page
          .getByRole("button", { name: language === "tr" ? "Gönder" : "Send", exact: true })
          .click();
        await expect(
          page.getByRole("listitem").filter({ hasText: byId.get(block.held[0]!)!.name }),
        ).toBeVisible();
        await page
          .getByRole("button", { name: language === "tr" ? "Planları hesapla" : "Compute plans" })
          .click();
        const cards = page.locator("article[data-plan-ready]");
        if (mode !== "enabled") {
          if (mode === "disabled") await expect.poll(() => jobs).toBe(1);
          else if (mode.startsWith("stale-")) {
            await expect(
              page.getByRole("status").filter({ hasText: LLMOPT_COPY[language].newSquad }),
            ).toBeVisible();
            await expect(
              page.getByRole("button", { name: LLMOPT_COPY[language].reload, exact: true }),
            ).toBeVisible();
            await expect(
              page.getByText(LLMOPT_COPY[language].serviceUnavailable, { exact: true }),
            ).toHaveCount(0);
          } else
            await expect(
              page.getByText(LLMOPT_COPY[language].serviceUnavailable, { exact: true }),
            ).toBeVisible();
          expect(jobs).toBe(mode === "disabled" ? 1 : 0);
          expect(workers).toBe(0);
          await expect(cards).toHaveCount(0);
          expect(
            await page.evaluate(() =>
              Object.keys(sessionStorage).some((key) => key.startsWith("llmopt-device-work-v1:")),
            ),
          ).toBe(false);
          return;
        }
        await expect(cards).toHaveCount(priority ? 2 : 3);
        expect(workers).toBeGreaterThan(0);
        const identities = await cards.evaluateAll((items) =>
          items.map((item) => item.getAttribute("data-transfer-decision")),
        );
        if (!priority) expect(new Set(identities).size).toBe(3);
        for (const identity of identities)
          expect(JSON.parse(identity!)[1]).toContain(block.held[0]);
        expect(jobs).toBe(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        );
        await page.reload();
        await holdModel(page);
        await expect(cards).toHaveCount(priority ? 2 : 3);
        expect(
          await cards.evaluateAll((items) =>
            items.map((item) => item.getAttribute("data-transfer-decision")),
          ),
        ).toEqual(identities);
        if (language === "en" && width === 1280) {
          release = "disabled";
          const beforeRollback = workers;
          await page.reload();
          await expect(cards).toHaveCount(priority ? 2 : 3);
          expect(
            await cards.evaluateAll((items) =>
              items.map((item) => item.getAttribute("data-transfer-decision")),
            ),
          ).toEqual(identities);
          expect(workers).toBe(beforeRollback);
        }
        expect(jobs).toBe(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        );
      });
  }

for (const enabled of [false, true]) {
  test(`an ordinary member preference link uses the server with the release setting ${enabled}`, async ({
    page,
  }) => {
    test.skip(!API, "API build required for the member preference route");
    await installLeagueMocks(page);
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
    const { table } = await serveDeviceMember(page);
    await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
      answer(route, {
        contract_version: "league_capabilities_v1",
        ...(enabled ? { llmopt_vnext: true } : {}),
        league_id: LEAGUE,
        capture_snapshot_id: table.source_snapshot_id,
        season: table.season,
        gameweek: table.gameweek,
        strategies: { "saf-puan": { requires_rival: false, windows: [1] } },
        preferences: { available: true },
        top100: { available: false, weights: [] },
        managers_word: { available: false },
      }),
    );
    const advice = `${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice`;
    await page.route(`${advice}**`, (route) =>
      route.request().method() === "POST"
        ? answer(route, { job_id: "member-preference-job", status: "queued" }, 202)
        : answer(route, { error: { code: "NOT_COMPUTED" } }, 404),
    );
    let workers = 0;
    page.on("worker", () => workers++);
    const member = `/league/${LEAGUE}/members/${ENTRY}?mode=saf-puan&window=1`;
    await page.goto(member);
    const local = page.getByRole("button", {
      name: MESSAGES.en.leagueMembers.deviceButton,
      exact: true,
    });
    await expect(local).toBeVisible();
    await page.goto(
      member + "&preferences=" + encodeURIComponent(JSON.stringify({ no_hits: true })),
    );
    const compute = page.getByRole("button", {
      name: MESSAGES.en.leagueMembers.computeButton,
      exact: true,
    });
    await expect(compute).toBeEnabled();
    await expect(local).toHaveCount(0);
    const [submitted] = await Promise.all([
      page.waitForRequest((r) => r.method() === "POST" && r.url().split("?")[0] === advice),
      compute.click(),
    ]);
    expect(submitted.postDataJSON()).toMatchObject({ window: 1, preferences: { no_hits: true } });
    expect(submitted.postDataJSON()).not.toHaveProperty("run");
    expect(workers).toBe(0);
  });
}
