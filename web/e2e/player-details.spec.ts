import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { mockEntryAdviceEnvelope } from "../src/fixtures/league";
import type { FixturesPayload } from "../src/features/fixtures/types";
import { atRest } from "./atRest";
import { installLeagueMocks, openCalendar } from "./leagueMocks";

const ENTRY = 35249001;
const PLAN = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
const PLAYER = PLAN.payload.starting_xi![0]!;

async function open(page: Page) {
  await installLeagueMocks(page);
  const plan = structuredClone(PLAN);
  plan.payload.role_forecast = {
    version: "football_role_forecast_v1",
    model_version: "football_composite_v1",
    calibration: "not_independently_verified",
    scope: "current_gameweek_fixtures",
    rows: [
      {
        player_id: PLAYER.player_id,
        name: PLAYER.name,
        fixture_id: 40,
        gameweek: plan.payload.gameweek,
        kickoff: "2026-10-24T14:00:00Z",
        expected_minutes: 67.5,
        status: "fitted_known_start_labels",
        captured_eligibility_multiplier: 1,
        news_applied: false,
      },
    ],
  };
  const calendar: Omit<ReturnType<typeof openCalendar>, "payload"> & { payload: FixturesPayload } =
    openCalendar();
  calendar.payload.source_snapshot_id = plan.payload.source_snapshot_id!;
  calendar.payload.gameweeks[0]!.fixtures = [
    {
      fixture_id: 40,
      kickoff_utc: "2026-10-24T14:00:00Z",
      finished: false,
      home_score: null,
      away_score: null,
      home: { team_id: 1, name: PLAYER.team, short_name: "HOM" },
      away: { team_id: 2, name: "Visitors", short_name: "VIS" },
    },
  ];
  await page.route("**/data/fixtures.json", (route) => route.fulfill({ json: calendar }));
  await page.route(`**/advice/${ENTRY}/saf-puan/1.json`, (route) => route.fulfill({ json: plan }));
  await page.goto(`/league/352490/members/${ENTRY}?mode=saf-puan&window=1#kadro`);
}

for (const [language, width] of [
  ["tr", 360],
  ["en", 1280],
] as const) {
  test(`player details open by touch and keyboard in ${language} at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page);
    if (language === "en")
      await page.getByRole("button", { name: "EN · English", exact: true }).click();
    const label = language === "tr" ? "Oyuncu ayrıntıları" : "Player details";
    const trigger = page.getByRole("button", { name: `${PLAYER.name}: ${label}`, exact: true });
    await trigger.scrollIntoViewIfNeeded();
    const box = await trigger.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);
    await trigger.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: PLAYER.name });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(
      language === "tr" ? "Beklenen dakika: 67,5" : "Expected minutes: 67.5",
    );
    expect((await new AxeBuilder({ page }).include("dialog").analyze()).violations).toEqual([]);
    expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`player-${language}.png`) });
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await trigger.click();
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: language === "tr" ? "Kapat" : "Close" }).click();
    await expect(trigger).toBeFocused();
    const bench = page.locator("[data-mark='bench']").getByRole("button").first();
    await bench.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.locator("dialog")).toContainText(
      language === "tr" ? "Beklenen puan" : "Expected points",
    );
  });
}

for (const reducedMotion of ["reduce", "no-preference"] as const) {
  test(`plan positions settle correctly with ${reducedMotion} motion`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion });
    await open(page);
    await atRest(page);
    await page.evaluate(() => {
      const original = Element.prototype.animate;
      const seen: string[] = [];
      Object.assign(window, { pitchMoves: seen });
      Element.prototype.animate = function (...args) {
        if (this instanceof HTMLElement && this.dataset.playerMotion)
          seen.push(this.dataset.playerMotion);
        return original.apply(this, args);
      };
    });
    const next = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
    next.payload.starting_xi = [...PLAN.payload.starting_xi!].reverse();
    next.payload.bench = PLAN.payload.bench;
    next.payload.source_snapshot_id = PLAN.payload.source_snapshot_id;
    await page.route(`**/advice/${ENTRY}/saf-puan/3.json`, (route) =>
      route.fulfill({ json: next }),
    );
    await page.getByRole("radio", { name: /^3 hafta/ }).click();
    await expect(page).toHaveURL(/window=3/);
    const defenders = next.payload.starting_xi!.filter((player) => player.position === "DEF");
    const line = page.locator("[data-line='def'] [data-player-motion]");
    await expect
      .poll(() =>
        line.evaluateAll((nodes) =>
          nodes.map((node) => (node as HTMLElement).dataset.playerMotion),
        ),
      )
      .toEqual(defenders.map((player) => String(player.player_id)));
    await atRest(page);
    const moves = await page.evaluate(
      () => (window as unknown as { pitchMoves: string[] }).pitchMoves,
    );
    if (reducedMotion === "reduce") expect(moves).toEqual([]);
    else expect(moves.length).toBeGreaterThan(0);
    expect(
      await line.evaluateAll((nodes) =>
        nodes.every((node) => getComputedStyle(node).transform === "none"),
      ),
    ).toBe(true);
  });
}
