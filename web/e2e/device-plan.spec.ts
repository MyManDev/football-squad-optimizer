import { expect, test } from "@playwright/test";

import fixture from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import { mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { installLeagueMocks } from "./leagueMocks";

// The whole device path in a real browser: the published inputs, the worker, the wasm
// solver served from the site's own assets, and the plan drawn on the page. The
// instance is the parity fixture's, so the answer on screen is the server's.
const ENTRY = 35249001;
const member = fixture.members[2]!;

test("a member's plan is solved on the device and drawn as a computation result", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installLeagueMocks(page);
  const squad = mockEntrySquadEnvelopes[ENTRY]!;
  const withInputs = {
    ...squad,
    payload: {
      ...squad.payload,
      source_snapshot_id: fixture.document.source_snapshot_id,
      device_plan: member.entry,
    },
  };
  await page.route(/\/data\/league\/entries\/35249001\.json(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(withInputs),
    }),
  );
  await page.route(/\/data\/league\/device-plan\.json(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "provisional_league_ui_v1",
        generated_at_utc: "2026-10-03T00:00:00Z",
        source_kind: "live",
        payload: fixture.document,
      }),
    }),
  );
  const wasm: string[] = [];
  // Every request made from the press onward; the page's own opening read of the
  // service's capabilities (mocked and refused by the league mocks) is before it.
  const requested: string[] = [];
  let pressed = false;
  page.on("request", (request) => {
    if (pressed) requested.push(request.url());
  });
  page.on("response", (response) => {
    if (response.url().endsWith(".wasm")) wasm.push(`${response.status()} ${response.url()}`);
  });

  await page.goto(`/league/members/${ENTRY}?mode=saf-puan&window=1`);
  const button = page.getByRole("button", { name: "Bu cihazda hesapla" });
  await expect(button).toBeVisible();
  pressed = true;
  await button.click();
  await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Hesap sonucu")).toBeVisible();
  // The transfers the server's reference names, by the names the document gives them.
  const names = new Map(fixture.document.players.map((p) => [p.id, p.name]));
  for (const move of member.reference.moves) {
    await expect(page.getByText(names.get(move.in!)!).first()).toBeVisible();
  }
  expect(wasm.some((line) => line.startsWith("200 ") && line.includes("/assets/"))).toBe(true);
  // Nothing left the site: from the press on, every request went to the site's own origin.
  expect(requested.length).toBeGreaterThan(0);
  const foreign = requested.filter((url) => !url.startsWith("http://127.0.0.1:4173/"));
  expect(foreign).toEqual([]);
});
