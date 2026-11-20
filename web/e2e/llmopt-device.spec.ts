import { expect, test, type Page, type Route } from "@playwright/test";
import fixture from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../src/fixtures/league";
import {
  checkedPreferences,
  preferenceScope,
  preferencesKey,
} from "../src/features/league/advice/decisionPreferences";
import { installLeagueMocks } from "./leagueMocks";
import { EXAMPLE_CLAIM, pickMember } from "./identity";
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
            { priority: false, mode: "later-worker-error" },
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
        const fault = mode === "later-worker-error";
        const delayed =
          (mode === "enabled" || fault) && !priority && language === "en" && width === 1280;
        if (delayed) {
          // Run the shipped WASM worker. Hold only messages produced after its main
          // plan so the browser can inspect the UI before the optional answers arrive.
          await page.addInitScript((fail) => {
            const Native = window.Worker;
            window.Worker = class extends Native {
              constructor(...args: ConstructorParameters<typeof Native>) {
                super(...args);
                const held: unknown[] = [];
                let main = false,
                  released = false;
                this.addEventListener(
                  "message",
                  (event: MessageEvent) => {
                    if (released) return;
                    if (!main) {
                      main = event.data?.kind === "plan";
                      return;
                    }
                    event.stopImmediatePropagation();
                    held.push(event.data);
                    if (event.data?.kind !== "answer") return;
                    document.documentElement.dataset.optionalWorkerFinished = "true";
                    window.addEventListener(
                      "release-optional-worker",
                      () => {
                        released = true;
                        if (fail) this.dispatchEvent(new ErrorEvent("error"));
                        else
                          for (const data of held)
                            this.dispatchEvent(new MessageEvent("message", { data }));
                      },
                      { once: true },
                    );
                  },
                  true,
                );
              }
            };
          }, fault);
        }
        let release = fault ? "enabled" : mode;
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
        if (mode !== "enabled" && !fault) {
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
        let mainDecision: string | null = null;
        if (delayed) {
          await expect(cards).toHaveCount(1);
          mainDecision = await cards.first().getAttribute("data-transfer-decision");
          await expect(page.locator("html")).toHaveAttribute(
            "data-optional-worker-finished",
            "true",
          );
          await expect(cards).toHaveCount(1);
          await expect(
            page.getByRole("button", { name: LLMOPT_COPY[language].computing, exact: true }),
          ).toBeDisabled();
          await page.evaluate(() => window.dispatchEvent(new Event("release-optional-worker")));
        }
        const expectedCards = fault ? 1 : priority ? 2 : 3;
        await expect(cards).toHaveCount(expectedCards);
        expect(workers).toBeGreaterThan(0);
        const identities = await cards.evaluateAll((items) =>
          items.map((item) => item.getAttribute("data-transfer-decision")),
        );
        if (delayed) {
          expect(identities[0]).toBe(mainDecision);
          await expect(
            page.getByRole("button", { name: LLMOPT_COPY[language].compute, exact: true }),
          ).toBeEnabled();
        }
        if (!priority) expect(new Set(identities).size).toBe(expectedCards);
        for (const identity of identities)
          expect(JSON.parse(identity!)[1]).toContain(block.held[0]);
        expect(jobs).toBe(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        );
        await page.reload();
        await holdModel(page);
        await expect(cards).toHaveCount(expectedCards);
        expect(
          await cards.evaluateAll((items) =>
            items.map((item) => item.getAttribute("data-transfer-decision")),
          ),
        ).toEqual(identities);
        if (language === "en" && width === 1280) {
          release = "disabled";
          const beforeRollback = workers;
          await page.reload();
          await expect(cards).toHaveCount(expectedCards);
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

for (const unavailable of ["blocked", "full"] as const) {
  test(`one-week confirmation uses the server when session storage is ${unavailable}`, async ({
    page,
  }) => {
    test.skip(!API, "API build required for the advice boundary.");
    await installLeagueMocks(page, { claim: null });
    await page.addInitScript((mode) => {
      localStorage.setItem("squadopt.language", "en");
      if (mode === "blocked") {
        Object.defineProperty(window, "sessionStorage", {
          get() {
            throw new DOMException("Blocked", "SecurityError");
          },
        });
      } else {
        const write = Storage.prototype.setItem;
        Storage.prototype.setItem = function (key, value) {
          if (this === window.sessionStorage) throw new DOMException("Full", "QuotaExceededError");
          write.call(this, key, value);
        };
      }
    }, unavailable);
    const { table } = await serveDeviceMember(page);
    const league = `${API}/api/v1/leagues/${LEAGUE}`;
    await page.route(`${league}/capabilities`, (route) =>
      answer(route, {
        contract_version: "league_capabilities_v1",
        llmopt_vnext: true,
        preference_bundles: { version: "llmopt_preference_bundle_v1" },
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
    let workers = 0;
    page.on("worker", () => workers++);
    const runIds: string[] = [];
    const answers = new Map<string, ReturnType<typeof mockEntryAdviceEnvelope>>();
    await page.route(`${league}/entries/${ENTRY}/advice**`, (route) => {
      const request = route.request();
      if (request.method() === "OPTIONS") return answer(route, null);
      if (request.method() === "GET") {
        const prefs = new URL(request.url()).searchParams.get("preferences");
        const result = answers.get(preferencesKey(checkedPreferences(JSON.parse(prefs ?? "{}"))));
        return result
          ? answer(route, result)
          : answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
      }
      const body = request.postDataJSON();
      expect(body.window).toBe(1);
      expect(body.run.run_id).toMatch(/^[0-9a-f]{32}$/);
      runIds.push(body.run.run_id);
      const result = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
      result.payload.preferences = checkedPreferences(body.preferences);
      result.payload.preferences_scope = preferenceScope(result.payload.preferences);
      answers.set(preferencesKey(result.payload.preferences), result);
      return answer(route, result);
    });
    await page.goto(`/league/${LEAGUE}/members/${ENTRY}/llmopt`);
    await pickMember(page, EXAMPLE_CLAIM, "en");
    await page
      .getByRole("combobox", { name: LLMOPT_COPY.en.window, exact: true })
      .selectOption("1");
    await page.getByRole("button", { name: LLMOPT_COPY.en.compute, exact: true }).click();
    const first = page.locator("article[data-plan-ready]").first();
    await expect(first).toBeVisible();
    expect(runIds.length).toBeGreaterThan(0);
    const pinned = await page.evaluate(
      () => JSON.parse(history.state.llmoptSession.raw).confirmation,
    );
    expect(pinned).toMatchObject({ runId: runIds[0], deviceRun: false, deviceAlternatives: false });
    const started = [...runIds];
    await page.reload();
    // A tab without storage asks for the member again. The run lives in the history entry.
    await pickMember(page, EXAMPLE_CLAIM, "en");
    await expect(first).toBeVisible();
    expect(runIds).toEqual(started);
    expect(workers).toBe(0);
  });
}
