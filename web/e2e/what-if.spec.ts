import { expect, test } from "@playwright/test";

import fixture from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import { mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";

// The what-if mode (#1132) on a 320 px phone, the narrowest width of the phone matrix: the
// device solves the member's week from the parity fixture's inputs, the mode starts from
// that plan, and the open panel is no wider than its card. The shell clips sideways
// overflow, so the page's own scroll width cannot show a panel that runs past it.
const ENTRY = 35249001;
const member = fixture.members[2]!;
const COPY = MESSAGES.tr.leagueMembers;

test("the open what-if panel fits its card at 320 px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
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
        payload: { ...fixture.document, league_id: squad.payload.league_id },
      }),
    }),
  );

  await page.goto(`/league/352490/members/${ENTRY}?mode=saf-puan&window=1`);
  await page.getByRole("button", { name: "Bu cihazda hesapla" }).click();
  await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });

  // The what-if is a page of its own; the sidebar's link keeps the plan the device solved.
  await page.getByRole("button", { name: MESSAGES.tr.shell.openMenu }).click();
  await page
    .locator("#sidebar nav")
    .getByRole("link", { name: MESSAGES.tr.shell.whatIf, exact: true })
    .click();
  const tool = page.getByRole("region", { name: COPY.whatIfTitle });
  await tool.getByRole("button", { name: COPY.whatIfStart }).click();
  const points = tool.locator("dt", { hasText: COPY.whatIfPoints }).locator("xpath=../dd");
  await expect(points).not.toHaveText(/^-/, { timeout: 30_000 });

  const sizes = await tool.evaluate((element) => ({
    scroll: element.scrollWidth,
    client: element.clientWidth,
  }));
  expect(sizes.scroll).toBe(sizes.client);
  const add = tool.getByRole("button", { name: COPY.whatIfAddButton });
  const box = await add.boundingBox();
  const card = await tool.boundingBox();
  expect(box!.x + box!.width).toBeLessThanOrEqual(card!.x + card!.width + 0.5);
});
