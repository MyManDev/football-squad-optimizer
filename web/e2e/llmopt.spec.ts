import { expect, test, type Route } from "@playwright/test";

import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks } from "./leagueMocks";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
const ENTRY = EXAMPLE_CLAIM.entryId;
const PAGE = `/league/${LEAGUE}/members/${ENTRY}/llmopt`;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, idempotency-key",
};

function answer(route: Route, json: unknown) {
  return route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: CORS })
    : route.fulfill({ json, headers: CORS });
}

test("the mobile sidebar opens LLMOPT as a reloadable team page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
  await page.goto("/fixtures");
  const shell = MESSAGES.en.shell;
  const sidebarLink = page.locator("#sidebar").getByRole("link", { name: shell.llmopt });
  await page.getByRole("button", { name: shell.openMenu }).click();
  await sidebarLink.click();
  await expect(page).toHaveURL(PAGE);
  const heading = page.getByRole("heading", { level: 1, name: shell.llmopt });
  await expect(heading).toBeVisible();

  await page.reload();
  await expect(heading).toBeVisible();
  await page.getByRole("button", { name: shell.openMenu }).click();
  await expect(sidebarLink).toHaveAttribute("aria-current", "page");
});

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test(`a new rule uses the page motion preference (${reducedMotion})`, async ({ page }) => {
    await installLeagueMocks(page);
    await page.emulateMedia({ reducedMotion });
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
    await page.goto(PAGE);
    const main = page.getByRole("main");
    const add = main.getByRole("button", { name: "Add rule" });
    await add.click();
    const rule = main.getByRole("listitem").filter({ hasText: "Roll the transfer" });
    await expect(rule).toBeVisible();
    const animations = await rule.evaluate((row) => {
      const style = getComputedStyle(row);
      return { name: style.animationName, duration: style.animationDuration };
    });
    if (reducedMotion === "reduce") expect(animations).toEqual({ name: "none", duration: "0s" });
    else {
      expect(animations.name).not.toBe("none");
      expect(animations.duration).toBe("0.2s");
    }
  });
}

test("interpretation previews the constraints before the two advice requests", async ({ page }) => {
  test.skip(!API, "API build required");
  await installLeagueMocks(page);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const players = [...squad.starting_xi, ...squad.bench].map((player) => ({
    id: player.player_id,
    name: player.name,
    team: player.team,
  }));
  const message = "No hits. Keep the free transfer if possible.";
  const posts: { preferences: Record<string, unknown>; window: number }[] = [];
  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, { season: squad.season, players }),
  );
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
    answer(route, {
      contract_version: "league_capabilities_v1",
      league_id: LEAGUE,
      capture_snapshot_id: squad.source_snapshot_id,
      season: squad.season,
      gameweek: squad.gameweek,
      strategies: { "saf-puan": { windows: [1], requires_rival: false } },
      top100: { available: false, weights: [] },
      managers_word: { available: false },
      preferences: { available: true },
    }),
  );
  await page.route(`${API}/api/v1/llmopt/intent`, async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toMatchObject({
        message,
        locale: "en",
        draft: { hard: [], soft: [] },
      });
    }
    await answer(route, {
      status: "draft",
      draft: { hard: [{ kind: "no_hits" }], soft: [{ kind: "hold_transfers" }] },
    });
  });
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, async (route) => {
    if (route.request().method() !== "POST") {
      await answer(route, {});
      return;
    }
    const body = route.request().postDataJSON() as (typeof posts)[number];
    posts.push(body);
    const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    if (body.preferences.hold_transfers === true) {
      envelope.payload.moves = [];
      envelope.payload.expected_gain_vs_hold = 0;
      envelope.payload.expected_own_points = 45;
    } else {
      envelope.payload.expected_own_points = 48;
      envelope.payload.moves = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3).payload.moves;
    }
    await answer(route, {
      ...envelope,
      payload: {
        ...envelope.payload,
        preferences: body.preferences,
        preferences_scope: "all_selected_weeks",
      },
    });
  });

  await page.goto(PAGE);
  await page.getByRole("textbox", { name: "Plan instructions" }).fill(message);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  const compute = page.getByRole("button", { name: "Compute plans" });
  const rules = page.getByRole("main").getByRole("listitem");
  await expect(rules.filter({ hasText: "No transfer hits" })).toBeVisible();
  await expect(rules.filter({ hasText: "Roll the transfer" })).toBeVisible();
  await expect(compute).toBeEnabled();
  expect(posts).toHaveLength(0);

  await compute.click();
  await expect.poll(() => posts.length).toBe(2);
  expect(posts).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        window: 1,
        preferences: expect.objectContaining({ no_hits: true }),
      }),
      expect.objectContaining({
        window: 1,
        preferences: expect.objectContaining({ no_hits: true, hold_transfers: true }),
      }),
    ]),
  );
  expect(posts.filter(({ preferences }) => preferences.hold_transfers === true)).toHaveLength(1);
  expect(JSON.stringify(posts)).not.toContain(message);
  await expect(page.getByRole("heading", { name: "Base plan" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Preferred plan" })).toBeVisible();
  await expect(page.getByText("Difference from first plan", { exact: true })).toBeVisible();
  const chat = page.getByRole("listitem").filter({ hasText: message });
  const preferred = page.getByRole("article").filter({ hasText: "Preferred plan" });
  expect(await chat.evaluate((row) => getComputedStyle(row).animationDuration)).toBe("0.2s");
  expect(await preferred.evaluate((card) => getComputedStyle(card).animationDuration)).toBe("0.4s");
});

test("clarification keeps the first request and pauses calculation", async ({ page }) => {
  test.skip(!API, "API build required");
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const requested = "Buy Smith.";
  const question = "Which team does Smith play for?";
  const reply = "Chelsea.";
  const playerId = 999;
  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, {
      season: squad.season,
      players: [{ id: playerId, name: "Smith", team: "Chelsea" }],
    }),
  );
  await page.route(`${API}/api/v1/llmopt/intent`, async (route) => {
    if (route.request().method() === "OPTIONS") return answer(route, null);
    const body = route.request().postDataJSON();
    if (body.message === requested) {
      return answer(route, { status: "clarification", message: question });
    }
    expect(body).toMatchObject({
      message: reply,
      clarification: { message: requested, question },
    });
    return answer(route, {
      status: "draft",
      draft: { hard: [{ kind: "include_player", player_id: playerId }], soft: [] },
    });
  });

  await page.goto(PAGE);
  const input = page.getByRole("textbox", { name: "Plan instructions" });
  const send = page.getByRole("button", { name: "Send", exact: true });
  await input.fill(requested);
  await send.click();
  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Compute plans" })).toBeDisabled();
  await input.fill(reply);
  await send.click();
  await expect(page.getByText("Include player · Smith", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Compute plans" })).toBeEnabled();
});
