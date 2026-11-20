import { expect, test, type Route } from "@playwright/test";
import fixture from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { installLeagueMocks } from "./leagueMocks";
import { EXAMPLE_CLAIM } from "./identity";
import { holdModel, routeChat } from "./llmoptChat";
import { LLMOPT_COPY } from "../src/features/league/llmopt/copy";
import type { PlanContext } from "../src/features/league/llmopt/planHistory";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const ENTRY = EXAMPLE_CLAIM.entryId,
  LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
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
    test(`computed plan identities survive selection, reload and undo (${language}, ${width})`, async ({
      page,
    }) => {
      test.skip(!API, "API build required");
      await installLeagueMocks(page);
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
      const original = mockEntrySquadEnvelopes[ENTRY]!,
        block = fixture.members[0]!.entry;
      const table = {
        ...structuredClone(fixture.document),
        league_id: LEAGUE,
        season: original.payload.season,
        gameweek: original.payload.gameweek,
        source_snapshot_id: original.payload.source_snapshot_id!,
      };
      const byId = new Map(table.players.map((p) => [p.id, p])),
        held = block.held.map((id) => byId.get(id)!);
      const chosen = [
        ...held.filter((p) => p.position === "GK").slice(0, 1),
        ...held.filter((p) => p.position === "DEF").slice(0, 3),
        ...held.filter((p) => p.position === "MID").slice(0, 4),
        ...held.filter((p) => p.position === "FWD").slice(0, 3),
      ];
      const starters = new Set(chosen.map((p) => p.id)),
        captain = chosen.find((p) => p.position === "MID")!.id;
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
      await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
        answer(route, {
          contract_version: "league_capabilities_v1",
          llmopt_vnext: true,
          league_id: LEAGUE,
          capture_snapshot_id: table.source_snapshot_id,
          season: table.season,
          gameweek: table.gameweek,
          strategies: { "saf-puan": { requires_rival: false, windows: [1] } },
          top100: { available: false, weights: [] },
          managers_word: { available: false },
        }),
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
      const originalPoints = table.players[0]!.expected_points;
      let swap: { out: number; incoming: number } | undefined;
      let jobs = 0,
        workers = 0,
        checks = 0;
      page.on("worker", () => workers++);
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
      await routeChat(page, API!, (route) => {
        if (route.request().method() === "OPTIONS") return answer(route, null);
        checks++;
        const body = route.request().postDataJSON() as {
          message: string;
          plan_context?: PlanContext;
        };
        if (!body.plan_context)
          return answer(route, {
            status: "draft",
            draft: {
              hard: [{ kind: "keep_player", player_id: block.held[0] }],
              soft: [],
              window: 1,
            },
          });
        expect(JSON.stringify(body.plan_context)).not.toMatch(
          /expected_points|bank_after|net_points/,
        );
        if (body.message === "swap") {
          const [first, second] = body.plan_context.plans;
          const a = first!.weeks[0]!.players,
            b = second!.weeks[0]!.players;
          swap = {
            out: a.find((id) => !b.includes(id))!,
            incoming: b.find((id) => !a.includes(id))!,
          };
          return answer(route, {
            status: "plan",
            command: {
              plan_id: first!.plan_id,
              action: "substitute",
              week: 1,
              player_id: swap.out,
              replacement_id: swap.incoming,
            },
          });
        }
        const plan_id = body.plan_context.plans[1]!.plan_id;
        if (body.message === "unknown")
          return answer(route, {
            status: "plan",
            command: { plan_id: "f".repeat(64), action: "select" },
          });
        if (body.message === "invent")
          return answer(route, {
            status: "plan",
            command: { plan_id, action: "select", score: 98765 },
          });
        if (body.message === "late") table.players[0]!.expected_points += 1;
        return answer(route, { status: "plan", command: { plan_id, action: "select" } });
      });
      const copy = LLMOPT_COPY[language];
      const send = async (text: string) => {
        await page.getByRole("textbox", { name: copy.chat }).fill(text);
        await page.getByRole("button", { name: copy.send, exact: true }).click();
      };
      await page.goto(`/league/${LEAGUE}/members/${ENTRY}/llmopt`);
      await holdModel(page);
      await send("Keep this player");
      await page.getByRole("button", { name: copy.compute, exact: true }).click();
      const cards = page.locator("article[data-plan-ready][data-plan-id]");
      await expect(cards).toHaveCount(3);
      const ids = await cards.evaluateAll((cards) =>
        cards.map((c) => c.getAttribute("data-plan-id")!),
      );
      expect(new Set(ids).size).toBe(3);
      for (const id of ids) expect(id).toMatch(/^[0-9a-f]{64}$/);
      const selected = page.locator("article[data-selected=true]");
      await send(language === "tr" ? "İkinci planı kullan" : "Use the second plan");
      await expect(selected).toHaveAttribute("data-plan-id", ids[1]!);
      const workBefore = workers;
      await page.reload();
      await holdModel(page);
      await expect(cards).toHaveCount(3);
      await expect(selected).toHaveAttribute("data-plan-id", ids[1]!);
      expect(
        await cards.evaluateAll((cards) => cards.map((c) => c.getAttribute("data-plan-id")!)),
      ).toEqual(ids);
      await page.getByRole("button", { name: copy.undoPlan, exact: true }).click();
      await expect(selected).toHaveAttribute("data-plan-id", ids[0]!);
      await page.getByRole("button", { name: copy.redoPlan, exact: true }).click();
      await expect(selected).toHaveAttribute("data-plan-id", ids[1]!);
      await page
        .getByRole("combobox", { name: copy.planHistory, exact: true })
        .selectOption(ids[0]!);
      await expect(selected).toHaveAttribute("data-plan-id", ids[0]!);
      await send("unknown");
      await expect(page.getByText(copy.planQuestion, { exact: true })).toBeVisible();
      await page.getByRole("button", { name: copy.dismissQuestion, exact: true }).click();
      await send("invent");
      await expect(page.getByText(copy.planQuestion, { exact: true })).toBeVisible();
      await expect(page.getByRole("main")).not.toContainText("98765");
      await page.getByRole("button", { name: copy.dismissQuestion, exact: true }).click();
      const beforeLate = checks;
      await send("late");
      await expect(page.getByText(copy.planQuestion, { exact: true })).toBeVisible();
      expect(checks).toBe(beforeLate + 1);
      await page.getByRole("button", { name: copy.dismissQuestion, exact: true }).click();
      const beforeStale = checks;
      await send("Use the second plan");
      await expect(page.getByText(copy.planQuestion, { exact: true })).toBeVisible();
      expect(checks).toBe(beforeStale);
      expect(jobs).toBe(0);
      expect(workers).toBe(workBefore);
      if (language === "en" && width === 1280) {
        await page.getByRole("button", { name: copy.dismissQuestion, exact: true }).click();
        table.players[0]!.expected_points = originalPoints;
        await send("swap");
        await page.getByRole("button", { name: copy.compute, exact: true }).click();
        await expect
          .poll(async () => {
            const raw = await cards.first().getAttribute("data-transfer-decision");
            if (!raw || !swap) return false;
            const ids = JSON.parse(raw)[1] as number[];
            return ids.includes(swap.incoming) && !ids.includes(swap.out);
          })
          .toBe(true);
        await expect(cards).toHaveCount(1);
        await expect(
          page.getByRole("region", { name: copy.revisionTitle, exact: true }),
        ).toBeVisible();
        const replacementId = await cards.first().getAttribute("data-plan-id");
        expect(replacementId).not.toBe(ids[0]);
        expect(workers).toBe(workBefore + 1);
        await page.reload();
        await holdModel(page);
        await expect(cards).toHaveCount(1);
        await expect(selected).toHaveAttribute("data-plan-id", replacementId!);
        await page
          .getByRole("combobox", { name: copy.planHistory, exact: true })
          .selectOption(ids[0]!);
        await expect(selected).toHaveAttribute("data-plan-id", ids[0]!);
        await page.reload();
        await holdModel(page);
        await expect(cards).toHaveCount(1);
        await expect(selected).toHaveAttribute("data-plan-id", ids[0]!);
        expect(workers).toBe(workBefore + 1);
        expect(jobs).toBe(0);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    });
  }
