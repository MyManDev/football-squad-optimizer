import { expect, test } from "@playwright/test";

import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";

/**
 * The duel's rows (#1133) in a browser: each row leads with the position in a 2.5rem column,
 * and the name starts after it. The full word ("goalkeeper", "orta saha") ran into the name,
 * so the row prints the short code and keeps the word for a screen reader.
 */
for (const language of ["tr", "en"] as const) {
  for (const width of [1280, 390]) {
    test(`no position runs into the player's name, in ${language} at ${width} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await installLeagueMocks(page);
      await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
      await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
      const members = MESSAGES[language].leagueMembers;
      await page.goto("/league/352490/members/35249001/duel");
      await expect(page.getByRole("heading", { level: 2, name: members.duelTitle })).toBeVisible();
      await page.getByRole("group", { name: members.duelPick }).getByRole("button").first().click();
      const rows = page.locator("[data-duel] li");
      await expect(rows).toHaveCount(22);
      const overlaps = await rows.evaluateAll((items) =>
        items.flatMap((item) => {
          const [position, name] = [...item.children] as HTMLElement[];
          // What the row shows first, a text or an element: its ink, not its 2.5rem box.
          const range = document.createRange();
          range.selectNode(position!.firstChild!);
          const shown = range.getBoundingClientRect();
          const text = name!.getBoundingClientRect();
          return shown.right <= text.left + 0.5
            ? []
            : [`${position!.firstChild!.textContent} / ${name!.textContent}`];
        }),
      );
      expect(overlaps).toEqual([]);
    });
  }
}
