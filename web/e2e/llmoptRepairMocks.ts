import { type Page, type Route } from "@playwright/test";
import fixture from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks, openCalendar } from "./leagueMocks";

export const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
export const ENTRY = EXAMPLE_CLAIM.entryId;
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
export const PAGE = `/league/${LEAGUE}/members/${ENTRY}/llmopt`;
export const ADVICE = `${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`;
export const DATA_ID = "a".repeat(64);
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, idempotency-key",
};

export const answer = (route: Route, json: unknown, status = 200) =>
  route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: CORS })
    : route.fulfill({ json, status, headers: CORS });
type Language = "tr" | "en";

export async function installMember(page: Page, language: Language, chipHistory = true) {
  await installLeagueMocks(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
  const original = mockEntrySquadEnvelopes[ENTRY]!;
  const block = { ...fixture.members[0]!.entry, bank_tenths: 26, free_transfers: 1 };
  const table = {
    ...fixture.document,
    league_id: LEAGUE,
    season: original.payload.season,
    gameweek: original.payload.gameweek,
    source_snapshot_id: original.payload.source_snapshot_id!,
  };
  const players = new Map(table.players.map((p) => [p.id, p]));
  const held = block.held.map((id) => players.get(id)!);
  const eleven = ["GK", "DEF", "MID", "FWD"].flatMap((position, i) =>
    held.filter((p) => p.position === position).slice(0, [1, 3, 4, 3][i]),
  );
  const xi = new Set(eleven.map((p) => p.id));
  const row = (p: (typeof held)[number]) => ({
    ...original.payload.starting_xi[0]!,
    player_id: p.id,
    name: p.name,
    short_name: p.short_name,
    team: p.team,
    position: p.position,
    expected_points: p.expected_points,
    is_captain: p === eleven[6],
    is_vice_captain: p === eleven[5],
  });
  const squad = {
    ...original.payload,
    device_plan: block,
    bank_tenths: block.bank_tenths,
    free_transfers: 1,
    free_transfers_known: true,
    starting_xi: eleven.map(row),
    bench: held.filter((p) => !xi.has(p.id)).map(row),
  };
  await page.route(`**/data/league/entries/${ENTRY}.json*`, (route) =>
    route.fulfill({ json: { ...original, payload: squad } }),
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
  const calendar = openCalendar();
  calendar.payload.gameweeks = [0, 1, 2].map((i) => ({
    gameweek: squad.gameweek + i,
    deadline_utc: "2999-01-01T00:00:00Z",
    fixtures: [],
  }));
  await page.route("**/data/fixtures.json", (route) => route.fulfill({ json: calendar }));
  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, {
      season: squad.season,
      players: table.players.map(({ id, name, team }) => ({ id, name, team })),
    }),
  );
  const release = { master: true, threeWeek: false, repairs: true };
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
      ...(release.threeWeek ? { llmopt_vnext_three_week: true } : {}),
      ...(release.master
        ? { llmopt_vnext: true, verified_repairs: release.repairs, plan_data_id: DATA_ID }
        : {}),
      chips: { held_by_entry: chipHistory ? { [ENTRY]: [] } : {} },
    }),
  );
  return { squad, block, held, players, release };
}

export async function instructions(page: Page, language: Language, text: string) {
  await page
    .getByRole("textbox", { name: language === "tr" ? "Plan talimatların" : "Plan instructions" })
    .fill(text);
  await page
    .getByRole("button", { name: language === "tr" ? "Gönder" : "Send", exact: true })
    .click();
}
export const checkButton = (page: Page, language: Language) =>
  page.getByRole("button", {
    name: language === "tr" ? "Değişiklikleri denetle" : "Check changes",
    exact: true,
  });
