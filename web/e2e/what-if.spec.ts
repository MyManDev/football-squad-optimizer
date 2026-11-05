import { expect, test, type Page } from "@playwright/test";

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

async function openWhatIf(page: Page) {
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
        payload: {
          ...fixture.document,
          league_id: squad.payload.league_id,
          players: fixture.document.players.map((player) =>
            player.id === member.reference.squad[0]
              ? { ...player, name: "Alexander Isak", short_name: "Isak" }
              : player,
          ),
        },
      }),
    }),
  );

  await page.goto(`/league/352490/members/${ENTRY}?mode=saf-puan&window=1`);
  await page.getByRole("button", { name: "Bu cihazda hesapla" }).click();
  await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });

  // The what-if is a page of its own; the sidebar's link keeps the plan the device solved.
  const menu = page.getByRole("button", { name: MESSAGES.tr.shell.openMenu });
  if (await menu.isVisible()) await menu.click();
  await page
    .locator("#sidebar nav")
    .getByRole("link", { name: MESSAGES.tr.shell.whatIf, exact: true })
    .click();
  const tool = page.getByRole("region", { name: COPY.whatIfTitle });
  await tool.getByRole("button", { name: COPY.whatIfStart }).click();
  const points = tool.locator("dt", { hasText: COPY.whatIfPoints }).locator("xpath=../dd");
  await expect(points).not.toHaveText(/^-/, { timeout: 30_000 });

  return tool;
}

test("the open what-if panel fits its card at 320 px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  const tool = await openWhatIf(page);
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

test("name search adds the chosen player and a tried squad survives navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const tool = await openWhatIf(page);
  const remove = () => tool.getByRole("button", { name: COPY.whatIfRemoveLabel("Isak") });
  await remove().click();
  const search = tool.getByRole("searchbox", { name: COPY.whatIfSearch });
  const list = tool.getByLabel(COPY.whatIfAdd, { exact: true });
  for (const query of ["isak", "ISAK", "İsak", "alexander isak"]) {
    await search.fill(query);
    await expect(list.locator("option[value='" + member.reference.squad[0] + "']")).toHaveCount(1);
  }
  await list.selectOption(String(member.reference.squad[0]));
  await expect(remove()).toHaveCount(0);
  await tool.getByRole("button", { name: COPY.whatIfAddButton }).click();
  await expect(remove()).toBeVisible();
  await remove().click();
  await page
    .locator("#sidebar nav")
    .getByRole("link", { name: MESSAGES.tr.shell.thisWeek, exact: true })
    .click();
  await page
    .locator("#sidebar nav")
    .getByRole("link", { name: MESSAGES.tr.shell.whatIf, exact: true })
    .click();
  await expect(tool.getByRole("button", { name: /^Kadrodan çıkar/ })).toHaveCount(14);
  await expect(remove()).toHaveCount(0);
  await tool.getByRole("button", { name: COPY.whatIfReset }).click();
  await expect(tool.getByRole("button", { name: /^Kadrodan çıkar/ })).toHaveCount(15);
});
