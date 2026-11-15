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
  const sidebar = page.locator("#sidebar");
  const sidebarLink = sidebar.getByRole("link", { name: shell.llmopt });
  await page.getByRole("button", { name: shell.openMenu }).click();
  const links = sidebar.getByRole("navigation").getByRole("link");
  await expect(links.nth(0)).toHaveAccessibleName(shell.live);
  await expect(links.nth(1)).toHaveAccessibleName(shell.llmopt);
  await expect(links.nth(2)).toHaveAccessibleName(shell.vsSquadopt);
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

for (const wildcardHeld of [true, false]) {
  test(`a preferred Wildcard in chat checks held chips (${wildcardHeld})`, async ({ page }) => {
    test.skip(!API, "API build required");
    await installLeagueMocks(page);
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
    const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
    const player = squad.starting_xi[0]!;
    const message = `Keep ${player.name} and play Wildcard if possible.`;
    const posts: { chip?: string; preferences: Record<string, unknown> }[] = [];
    await page.route(`${API}/api/v1/contributions/players`, (route) =>
      answer(route, {
        season: squad.season,
        players: [{ id: player.player_id, name: player.name, team: player.team }],
      }),
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
        chips: { held_by_entry: { [ENTRY]: wildcardHeld ? ["wildcard"] : [] } },
      }),
    );
    await page.route(`${API}/api/v1/llmopt/intent`, (route) =>
      answer(route, {
        status: "draft",
        draft: {
          hard: [{ kind: "keep_player", player_id: player.player_id }],
          soft: [{ kind: "wildcard" }],
        },
      }),
    );
    await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
      if (route.request().method() !== "POST") return answer(route, null);
      const body = route.request().postDataJSON() as (typeof posts)[number];
      posts.push(body);
      const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
      const chip = body.chip === "wildcard" ? "wildcard" : null;
      return answer(route, {
        ...envelope,
        payload: {
          ...envelope.payload,
          chip,
          ...(chip
            ? { chip_choice: { chip, gain_vs_no_chip: 0, basis: "expected_net_points" } }
            : {}),
          preferences: body.preferences,
          preferences_scope: "all_selected_weeks",
        },
      });
    });

    await page.goto(PAGE);
    await page.getByRole("textbox", { name: "Plan instructions" }).fill(message);
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.getByRole("button", { name: "Remove · Play Wildcard" })).toBeVisible();
    expect(posts).toHaveLength(0);
    await page.getByRole("button", { name: "Compute plans" }).click();

    await expect.poll(() => posts.length).toBe(wildcardHeld ? 2 : 1);
    await expect(page.getByRole("heading", { name: "Base plan" })).toBeVisible();
    expect(posts.find(({ chip }) => chip === undefined)?.preferences).toMatchObject({
      save_chips: true,
      keep_players: [player.player_id],
    });
    if (wildcardHeld) {
      expect(posts.find(({ chip }) => chip === "wildcard")?.preferences).toMatchObject({
        save_chips: false,
        keep_players: [player.player_id],
      });
      await expect(page.getByRole("heading", { name: "Preferred plan" })).toBeVisible();
      await expect(page.getByText("Difference from first plan")).toBeVisible();
    } else {
      await expect(
        page.getByText("This team cannot play its Wildcard this gameweek."),
      ).toBeVisible();
      await expect(page.getByRole("heading", { name: "Preferred plan" })).toHaveCount(0);
    }
  });
}

test("a Turkish club request lets the optimizer pick the three players", async ({ page }) => {
  test.skip(!API, "API build required");
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const message = "Wildcard kullan, Brighton'dan 3 oyuncu al. Oyuncuları sen seç.";
  const clubCount = { club: "Brighton", count: 3, scope: "transfers_in" };
  const posts: {
    chip: string;
    preferences: { club_counts?: unknown; include_players?: number[] };
  }[] = [];
  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, {
      season: squad.season,
      players: [
        { id: 501, name: "First Player", team: "Brighton" },
        { id: 502, name: "Second Player", team: "Brighton" },
        { id: 503, name: "Third Player", team: "Brighton" },
      ],
    }),
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
      chips: { available: ["wildcard"], held_by_entry: { [ENTRY]: ["wildcard"] } },
    }),
  );
  await page.route(`${API}/api/v1/llmopt/intent`, (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toMatchObject({ message, locale: "tr" });
    }
    return answer(route, {
      status: "draft",
      draft: { hard: [{ kind: "wildcard" }, { kind: "club_count", ...clubCount }], soft: [] },
    });
  });
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
    if (route.request().method() !== "POST") return answer(route, null);
    const body = route.request().postDataJSON() as (typeof posts)[number];
    posts.push(body);
    const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    return answer(route, {
      ...envelope,
      payload: {
        ...envelope.payload,
        chip: "wildcard",
        preferences: body.preferences,
        preferences_scope: "all_selected_weeks",
      },
    });
  });

  await page.goto(PAGE);
  await page.getByRole("textbox", { name: "Plan talimatların" }).fill(message);
  await page.getByRole("button", { name: "Gönder", exact: true }).click();
  await expect(page.getByRole("button", { name: "Kaldır · Wildcard kullan" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Kaldır · Brighton · Gelen transferler · 3" }),
  ).toBeVisible();
  expect(posts).toHaveLength(0);
  await page.getByRole("button", { name: "Planları hesapla" }).click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0]?.chip).toBe("wildcard");
  expect(posts[0]?.preferences.club_counts).toEqual([clubCount]);
  expect(posts[0]?.preferences.include_players).toBeUndefined();
  await expect(page.getByRole("heading", { name: "Temel plan" })).toBeVisible();
});

test("a Turkish plan holds now, buys next week and caps three weeks of hits", async ({ page }) => {
  test.skip(!API, "API build required");
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const outgoing = squad.starting_xi.find((player) => player.position === "MID")!;
  const incoming = { ...outgoing, player_id: 9081321, name: "Bukayo Saka", team: "Arsenal" };
  const message =
    "Bu hafta transferi sakla, haftaya Saka'yı al. Üç haftada en fazla 4 puan ceza öde.";
  const posts: { window: number; preferences: Record<string, unknown> }[] = [];
  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, {
      season: squad.season,
      players: [{ id: incoming.player_id, name: incoming.name, team: incoming.team }],
    }),
  );
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
    answer(route, {
      contract_version: "league_capabilities_v1",
      league_id: LEAGUE,
      capture_snapshot_id: squad.source_snapshot_id,
      season: squad.season,
      gameweek: squad.gameweek,
      strategies: { "saf-puan": { windows: [1, 3], requires_rival: false } },
      top100: { available: false, weights: [] },
      managers_word: { available: false },
      preferences: { available: true },
    }),
  );
  await page.route(`${API}/api/v1/llmopt/intent`, (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toMatchObject({ message, locale: "tr" });
    }
    return answer(route, {
      status: "draft",
      draft: {
        window: 3,
        hard: [
          { kind: "hold_transfers", week: 1 },
          { kind: "buy_player", player_id: incoming.player_id, week: 2 },
          { kind: "hit_budget", points: 4 },
        ],
        soft: [],
      },
    });
  });
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
    if (route.request().method() !== "POST") return answer(route, null);
    const body = route.request().postDataJSON() as (typeof posts)[number];
    posts.push(body);
    const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
    return answer(route, {
      ...envelope,
      payload: {
        ...envelope.payload,
        moves: [],
        plan_weeks: envelope.payload.plan_weeks!.map((week, i) => ({
          ...week,
          gameweek: squad.gameweek + i,
          transfers_in: i === 1 ? [incoming] : [],
          transfers_out: i === 1 ? [outgoing] : [],
          transfer_hit_points: i === 1 ? 4 : 0,
          expected_points: [42, 49, 44][i]!,
        })),
        preferences: body.preferences,
        preferences_scope: "selected_weeks",
      },
    });
  });

  await page.goto(PAGE);
  await page.getByRole("textbox", { name: "Plan talimatların" }).fill(message);
  await page.getByRole("button", { name: "Gönder", exact: true }).click();
  await expect(page.getByLabel("Plan süresi")).toHaveValue("3");
  await expect(
    page.getByRole("button", { name: "Kaldır · Transferi sakla · Bu hafta" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Kaldır · Oyuncuyu transfer et · Bukayo Saka · 2. hafta" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Kaldır · Toplam ceza sınırı · 4 puan" }),
  ).toBeVisible();
  expect(posts).toHaveLength(0);
  await page.getByRole("button", { name: "Planları hesapla" }).click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0]).toMatchObject({
    window: 3,
    preferences: {
      week_rules: [
        { week: 1, rules: { hold_transfers: true } },
        { week: 2, rules: { buy_players: [incoming.player_id] } },
      ],
      max_hit_points: 4,
    },
  });
  const plan = page.locator("article[data-plan-ready]");
  await expect(plan.locator("[data-player-motion]")).toHaveCount(15);
  await expect(plan.getByText("Toplam beklenen net puan", { exact: true })).toBeVisible();
  const later = plan.getByRole("region", { name: "Önümüzdeki haftalar" });
  await expect(later.getByRole("heading", { name: `GW ${squad.gameweek + 1}` })).toBeVisible();
  await expect(later.getByRole("heading", { name: `GW ${squad.gameweek + 2}` })).toBeVisible();
  await expect(later.getByText(incoming.name, { exact: true })).toBeVisible();
});

test("a future Wildcard is checked on its own week", async ({ page }) => {
  test.skip(!API, "API build required");
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const player = squad.starting_xi[0]!;
  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, {
      season: squad.season,
      players: [{ id: player.player_id, name: player.name, team: player.team }],
    }),
  );
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
    answer(route, {
      contract_version: "league_capabilities_v1",
      league_id: LEAGUE,
      capture_snapshot_id: squad.source_snapshot_id,
      season: squad.season,
      gameweek: squad.gameweek,
      strategies: { "saf-puan": { windows: [1, 3], requires_rival: false } },
      preferences: { available: true },
      top100: { available: false, weights: [] },
      managers_word: { available: false },
      chips: { held_by_entry: { [ENTRY]: [] } },
    }),
  );
  await page.route(`${API}/api/v1/llmopt/intent`, (route) =>
    answer(route, {
      status: "draft",
      draft: { window: 3, hard: [{ kind: "wildcard", week: 2 }], soft: [] },
    }),
  );
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
    if (route.request().method() !== "POST") return answer(route, null);
    const body = route.request().postDataJSON();
    expect(body).toMatchObject({ window: 3, preferences: { wildcard_week: 2 } });
    expect(body.chip ?? null).toBeNull();
    const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
    return answer(route, {
      ...envelope,
      payload: {
        ...envelope.payload,
        chip: null,
        chip_strategy: {
          version: "dated_joint_opportunity_v3",
          mode: "manual",
          requested_chip: "wildcard",
          selected_chip: null,
          top100_weight: 0,
          objective_gap: null,
          objective_basis: "selection_utility_with_chip_reserve",
          experimental: false,
          reservations: [],
          limits: [],
        },
        plan_weeks: envelope.payload.plan_weeks!.map((week, i) => ({
          ...week,
          gameweek: squad.gameweek + i,
          chip: i === 1 ? "wildcard" : null,
        })),
        preferences: body.preferences,
        preferences_scope: "selected_weeks",
      },
    });
  });
  await page.goto(PAGE);
  await page.getByRole("textbox", { name: "Plan talimatların" }).fill("Wildcard'ı haftaya kullan.");
  await page.getByRole("button", { name: "Gönder", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Kaldır · Wildcard kullan · 2. hafta" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Planları hesapla" }).click();
  const later = page
    .locator("article[data-plan-ready]")
    .getByRole("region", { name: "Önümüzdeki haftalar" });
  await expect(later.getByText("Wildcard", { exact: true })).toBeVisible();
});

test("three-week alternatives preserve hard rules and offer different opening moves", async ({
  page,
}) => {
  test.skip(!API, "API build required");
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const outgoing = squad.starting_xi.find((player) => player.position === "MID")!;
  const protectedPlayer = squad.starting_xi.find((player) => player.position === "GK")!;
  const baseSigning = { ...outgoing, player_id: 9081320, name: "Main Signing" };
  const budgetSigning = { ...outgoing, player_id: 9081322, name: "Budget Signing" };
  const posts: { window: number; preferences: Record<string, unknown> }[] = [];
  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, {
      season: squad.season,
      players: [
        { id: protectedPlayer.player_id, name: protectedPlayer.name, team: protectedPlayer.team },
      ],
    }),
  );
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
    answer(route, {
      contract_version: "league_capabilities_v1",
      league_id: LEAGUE,
      capture_snapshot_id: squad.source_snapshot_id,
      season: squad.season,
      gameweek: squad.gameweek,
      strategies: { "saf-puan": { windows: [1, 3], requires_rival: false } },
      preferences: { available: true },
      top100: { available: false, weights: [] },
      managers_word: { available: false },
    }),
  );
  await page.route(`${API}/api/v1/llmopt/intent`, (route) =>
    answer(route, {
      status: "draft",
      draft: {
        window: 3,
        hard: [{ kind: "keep_player", player_id: protectedPlayer.player_id }, { kind: "no_hits" }],
        soft: [],
      },
    }),
  );
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
    if (route.request().method() !== "POST") return answer(route, null);
    const body = route.request().postDataJSON() as (typeof posts)[number];
    posts.push(body);
    const roll = body.preferences.hold_opening_transfers === true;
    const budget = body.preferences.min_opening_bank_tenths !== undefined;
    const signing = budget ? budgetSigning : baseSigning;
    const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
    const payload = {
      ...envelope.payload,
      moves: roll
        ? []
        : [{ ...envelope.payload.moves[0]!, player_in: signing, player_out: outgoing }],
      starting_xi: squad.starting_xi.map((player) =>
        !roll && player.player_id === outgoing.player_id ? signing : player,
      ),
      bank_after_tenths: budget ? 17 : 6,
      free_transfers_after: roll ? 2 : 1,
      plan_weeks: envelope.payload.plan_weeks!.map((week, i) => ({
        ...week,
        gameweek: squad.gameweek + i,
        transfers_in: !roll && i === 0 ? [signing] : [],
        transfers_out: !roll && i === 0 ? [outgoing] : [],
        free_transfers_after: roll ? 2 : 1,
        chip: null,
        transfer_hit_points: 0,
        expected_points: i === 0 ? (roll ? 42 : budget ? 43 : 45) : 44,
      })),
      preferences: body.preferences,
      preferences_scope: roll || budget ? "selected_weeks" : "all_selected_weeks",
    };
    return answer(route, { ...envelope, payload });
  });

  await page.goto(PAGE);
  await page
    .getByRole("textbox", { name: "Plan talimatların" })
    .fill("Üç haftalık plan yap. Kalecim kalsın ve puan cezası alma.");
  await page.getByRole("button", { name: "Gönder", exact: true }).click();
  await expect(page.getByLabel("Plan süresi")).toHaveValue("3");
  expect(posts).toHaveLength(0);
  await page.getByRole("button", { name: "Planları hesapla" }).click();
  const cards = page.locator("article[data-plan-ready]");
  await expect(cards).toHaveCount(3);
  expect(posts).toHaveLength(3);
  expect(posts[0]?.preferences.hold_opening_transfers).toBeUndefined();
  expect(posts[0]?.preferences.min_opening_bank_tenths).toBeUndefined();
  expect(posts.slice(1).map(({ preferences }) => preferences)).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ hold_opening_transfers: true }),
      expect.objectContaining({ min_opening_bank_tenths: 7 }),
    ]),
  );
  for (const posted of posts) {
    expect(posted).toMatchObject({
      window: 3,
      preferences: { keep_players: [protectedPlayer.player_id], no_hits: true },
    });
  }
  await expect(cards.first().getByRole("heading", { name: "Temel plan" })).toBeVisible();
  await expect(
    cards.filter({ has: page.getByRole("heading", { name: /transferi sakla/i }) }),
  ).toHaveCount(1);
  await expect(
    cards.filter({ has: page.getByRole("heading", { name: /bütçe|kasa/i }) }),
  ).toHaveCount(1);
  await expect(cards.filter({ hasText: "Main Signing" })).toHaveCount(1);
  await expect(cards.filter({ hasText: "Budget Signing" })).toHaveCount(1);
  await expect(cards.getByText("Toplam beklenen net puan", { exact: true })).toHaveCount(3);
});

test("preferred players are priced individually and only shown within their exact limit", async ({
  page,
}) => {
  test.skip(!API, "API build required");
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const outgoing = squad.starting_xi.find((player) => player.position === "MID")!;
  const players = [
    { ...outgoing, player_id: 9081321, name: "Bukayo Saka", team: "Arsenal" },
    { ...outgoing, player_id: 9081322, name: "Second Target" },
  ];
  const message =
    "Üç haftalık ve cezasız plan yap. Saka ve Second Target için ayrı ayrı 1,5 puana kadarlık farkı kabul ediyorum.";
  const posts: { window: number; preferences: Record<string, unknown> }[] = [];
  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, {
      season: squad.season,
      players: players.map(({ player_id, name, team }) => ({ id: player_id, name, team })),
    }),
  );
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
    answer(route, {
      contract_version: "league_capabilities_v1",
      league_id: LEAGUE,
      capture_snapshot_id: squad.source_snapshot_id,
      season: squad.season,
      gameweek: squad.gameweek,
      strategies: { "saf-puan": { windows: [1, 3], requires_rival: false } },
      preferences: { available: true },
      top100: { available: false, weights: [] },
      managers_word: { available: false },
    }),
  );
  await page.route(`${API}/api/v1/llmopt/intent`, (route) =>
    answer(route, {
      status: "draft",
      draft: {
        window: 3,
        hard: [{ kind: "no_hits" }],
        soft: players.map(({ player_id }) => ({
          kind: "include_player",
          player_id,
          max_cost_tenths: 15,
        })),
      },
    }),
  );
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
    if (route.request().method() !== "POST") return answer(route, null);
    const body = route.request().postDataJSON() as (typeof posts)[number];
    posts.push(body);
    const preferred = (body.preferences.include_players as number[] | undefined)?.[0];
    const signing = players.find((p) => p.player_id === preferred);
    const firstWeekPoints = signing === players[0] ? 43.6 : signing === players[1] ? 43.46 : 45;
    const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
    const move = signing
      ? [{ ...envelope.payload.moves[0]!, player_in: signing, player_out: outgoing }]
      : [];
    return answer(route, {
      ...envelope,
      payload: {
        ...envelope.payload,
        solver_status: signing === players[1] ? "FEASIBLE" : "OPTIMAL",
        moves: move,
        starting_xi: squad.starting_xi.map((player) =>
          signing && player.player_id === outgoing.player_id ? signing : player,
        ),
        plan_weeks: envelope.payload.plan_weeks!.map((week, i) => ({
          ...week,
          gameweek: squad.gameweek + i,
          transfers_in: signing && i === 0 ? [signing] : [],
          transfers_out: signing && i === 0 ? [outgoing] : [],
          chip: null,
          transfer_hit_points: 0,
          expected_points: i === 0 ? firstWeekPoints : 44,
        })),
        preferences: body.preferences,
        preferences_scope: "all_selected_weeks",
      },
    });
  });

  await page.goto(PAGE);
  await page.getByRole("textbox", { name: "Plan talimatların" }).fill(message);
  await page.getByRole("button", { name: "Gönder", exact: true }).click();
  await expect(
    page.getByRole("button", {
      name: "Kaldır · Oyuncuyu kadroya al · Bukayo Saka · En fazla 1,5 puan",
    }),
  ).toBeVisible();
  expect(posts).toHaveLength(0);
  await page.getByRole("button", { name: "Planları hesapla" }).click();
  await expect(
    page.getByText("Belirlediğin puan sınırının üzerinde.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/1,4(?:00)? beklenen puan kaybı/)).toBeVisible();
  await expect(page.getByText(/1,54(?:0)? beklenen puan kaybı/)).toBeVisible();
  expect(posts).toHaveLength(3);
  expect(posts[0]?.preferences.include_players).toBeUndefined();
  expect(posts.slice(1).map(({ preferences }) => preferences.include_players)).toEqual(
    expect.arrayContaining(players.map(({ player_id }) => [player_id])),
  );
  for (const post of posts) {
    expect(post).toMatchObject({
      window: 3,
      preferences: { net_points_priority: true, no_hits: true },
    });
    expect(JSON.stringify(post)).not.toContain("max_cost_tenths");
  }
  const cards = page.locator("article[data-plan-ready]");
  await expect(cards).toHaveCount(2);
  await expect(cards.getByRole("heading", { name: /Tercihli plan.*Bukayo Saka/i })).toHaveCount(1);
  await expect(cards.getByRole("heading", { name: /Tercihli plan.*Second Target/i })).toHaveCount(
    0,
  );
});
