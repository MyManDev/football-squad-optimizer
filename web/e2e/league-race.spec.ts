import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { MESSAGES } from "../src/i18n/messages";
import { shippedTrees } from "../src/testSupport/shippedTrees";
import { shippedClaim } from "./identity";
import { installLeagueMocks } from "./leagueMocks";

// The league race (#1135) on the narrowest phones of the matrix, with a manager name of 40
// characters (names may run to 64): the card stays inside its column, so every place-change
// count is on screen. The shell clips sideways overflow, so the page's own scroll width
// cannot show a card that runs past it; the card's scroll width can.
const LONG = "Abdurrahman Alparslan Karamanoğlu Sezgin";

for (const width of [320, 360]) {
  test(`the race card fits its column at ${width} px with a long manager name`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 800 });
    // The viewer is the shipped league's first member, the table served below being its own.
    await installLeagueMocks(page, { claim: shippedClaim() });
    // The shipped tree's table, the one the shipped scoreboard the mocks serve belongs to.
    const root = shippedTrees()[0]!.root;
    const table = JSON.parse(readFileSync(join(root, "members.json"), "utf-8"));
    const first = table.payload.members.find(
      (member: { member_kind: string }) => member.member_kind === "human",
    );
    first.manager_name = LONG;
    await page.route("**/data/league/members.json", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(table) }),
    );
    await page.goto("/league/352490/members");
    const race = page.getByRole("region", { name: MESSAGES.tr.leagueMembers.raceTitle });
    await expect(race).toBeVisible();
    const sizes = await race.evaluate((element) => ({
      scroll: element.scrollWidth,
      client: element.clientWidth,
    }));
    expect(sizes.scroll).toBe(sizes.client);
    const card = (await race.boundingBox())!;
    for (const count of await race.locator("li[data-move] span:last-child").all()) {
      const box = (await count.boundingBox())!;
      expect(box.x + box.width).toBeLessThanOrEqual(card.x + card.width + 0.5);
    }
  });
}
