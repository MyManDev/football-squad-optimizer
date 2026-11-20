import { expect, test, type Route } from "@playwright/test";
import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../src/fixtures/league";
import type { DecisionPreferences } from "../src/features/league/advice/decisionPreferences";
import { preferenceScope } from "../src/features/league/advice/decisionPreferences";
import { installLeagueMocks, openCalendar } from "./leagueMocks";
import { EXAMPLE_CLAIM } from "./identity";
import { holdModel, routeChat } from "./llmoptChat";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
const ENTRY = EXAMPLE_CLAIM.entryId;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, idempotency-key",
};
const answer = (route: Route, json: unknown) =>
  route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: CORS })
    : route.fulfill({ json, headers: CORS });

for (const enabled of [false, true])
  for (const language of ["en", "tr"] as const) {
    test(`three-week paths stay bounded across reload (${enabled}, ${language})`, async ({
      page,
    }) => {
      test.skip(!API, "API build required");
      await installLeagueMocks(page);
      await page.setViewportSize({ width: language === "tr" ? 375 : 1280, height: 900 });
      await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
      const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
      const posts: DecisionPreferences[] = [];
      const runIds: string[] = [];
      let reads = 0;
      let advertised = enabled;
      await page.route("**/data/fixtures.json", (route) => route.fulfill({ json: openCalendar() }));
      await page.route(`${API}/api/v1/contributions/players`, (route) =>
        answer(route, {
          season: squad.season,
          players: [...squad.starting_xi, ...squad.bench].map((p) => ({
            id: p.player_id,
            name: p.name,
            team: p.team,
          })),
        }),
      );
      await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
        answer(route, {
          contract_version: "league_capabilities_v1",
          llmopt_vnext: true,
          league_id: LEAGUE,
          capture_snapshot_id: squad.source_snapshot_id,
          season: squad.season,
          gameweek: squad.gameweek,
          strategies: { "saf-puan": { windows: [1, 3], requires_rival: false } },
          top100: { available: false, weights: [] },
          managers_word: { available: false },
          preferences: { available: true },
          ...(advertised ? { transfer_packages: true } : {}),
        }),
      );
      await routeChat(page, API, (route) =>
        answer(route, {
          status: "draft",
          draft: { window: 3, hard: [{ kind: "no_hits" }], soft: [] },
        }),
      );
      const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
      const incoming = base.payload.plan_weeks![0]!.transfers_in;
      const outgoing = base.payload.plan_weeks![0]!.transfers_out;
      await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
        if (route.request().method() === "OPTIONS") return answer(route, null);
        const preferences = JSON.parse(
          new URL(route.request().url()).searchParams.get("preferences")!,
        ) as DecisionPreferences;
        if (route.request().method() === "POST") {
          posts.push(preferences);
          runIds.push(route.request().postDataJSON().run?.run_id ?? "missing");
        } else reads++;
        const envelope = structuredClone(base);
        const weeks = envelope.payload.plan_weeks!;
        for (const week of weeks) {
          week.chip = null;
          week.transfer_hit_points = 0;
        }
        const alternative =
          preferences.hold_opening_transfers || preferences.min_opening_bank_tenths !== undefined;
        if (alternative) {
          weeks[0]!.transfers_in = [];
          weeks[0]!.transfers_out = [];
          weeks[0]!.free_transfers_after = 2;
          envelope.payload.moves = [];
        }
        if (preferences.week_rules?.find((w) => w.week === 2)?.rules.buy_players?.length) {
          weeks[1]!.transfers_in = incoming;
          weeks[1]!.transfers_out = outgoing;
        }
        envelope.payload.bank_after_tenths = alternative ? 30 : 20;
        envelope.payload.preferences = preferences;
        envelope.payload.preferences_scope = preferenceScope(preferences);
        return answer(route, envelope);
      });
      await page.goto(`/league/${LEAGUE}/members/${ENTRY}/llmopt`);
      await holdModel(page);
      await page
        .getByRole("textbox", {
          name: language === "tr" ? "Plan talimatların" : "Plan instructions",
        })
        .fill("Plan three weeks with no hits.");
      await page
        .getByRole("button", { name: language === "tr" ? "Gönder" : "Send", exact: true })
        .click();
      const compute = page.getByRole("button", {
        name: language === "tr" ? "Planları hesapla" : "Compute plans",
      });
      await expect(compute).toBeEnabled();
      await compute.click();
      await expect.poll(() => posts.length).toBe(3);
      // The legacy view deduplicates equal opening decisions. Enabled paths keep
      // distinct later purchases and group their shared opening together.
      await expect(page.getByRole("article")).toHaveCount(enabled ? 3 : 2);
      const delayed = posts.find((p) => p.hold_opening_transfers);
      expect(delayed).toBeDefined();
      expect(delayed?.week_rules?.find((w) => w.week === 2)?.rules.buy_players).toEqual(
        enabled ? incoming.map((p) => p.player_id) : undefined,
      );
      expect(posts.every((p) => p.no_hits)).toBe(true);
      expect(new Set(runIds).size).toBe(1);
      expect(runIds[0]).toMatch(/^[0-9a-f]{32}$/);
      await expect(page.locator("[data-path-group]")).toHaveCount(enabled ? 2 : 0);
      // A changed capability does not change this already confirmed run.
      advertised = !enabled;
      await page.reload();
      await expect(page.getByRole("article")).toHaveCount(enabled ? 3 : 2);
      await expect.poll(() => reads).toBe(3);
      expect(posts).toHaveLength(3);
      await expect(page.locator("[data-path-group]")).toHaveCount(enabled ? 2 : 0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    });
  }
