import { expect, test, type Route } from "@playwright/test";
import fixture from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { installLeagueMocks } from "./leagueMocks";
import { EXAMPLE_CLAIM } from "./identity";
import { holdModel, routeChat } from "./llmoptChat";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const ENTRY = EXAMPLE_CLAIM.entryId;
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, idempotency-key",
};
const answer = (route: Route, json: unknown) =>
  route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: CORS })
    : route.fulfill({ json, headers: CORS });

for (const language of ["en", "tr"] as const)
  for (const width of [1280, 375]) {
    test(`device choices obey hard rules and reload without jobs (${language}, ${width})`, async ({
      page,
    }) => {
      test.skip(!API, "API build required for the interpretation boundary.");
      await installLeagueMocks(page);
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
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
      let jobs = 0;
      await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
        if (route.request().method() === "POST") jobs++;
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
          draft: { hard: [{ kind: "keep_player", player_id: block.held[0] }], soft: [], window: 1 },
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
      await expect(cards).toHaveCount(3);
      const identities = await cards.evaluateAll((items) =>
        items.map((item) => item.getAttribute("data-transfer-decision")),
      );
      expect(new Set(identities).size).toBe(3);
      for (const identity of identities) expect(JSON.parse(identity!)[1]).toContain(block.held[0]);
      expect(jobs).toBe(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.reload();
      await holdModel(page);
      await expect(cards).toHaveCount(3);
      expect(
        await cards.evaluateAll((items) =>
          items.map((item) => item.getAttribute("data-transfer-decision")),
        ),
      ).toEqual(identities);
      expect(jobs).toBe(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    });
  }
