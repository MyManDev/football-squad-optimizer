import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

import { LLMOPT_COPY } from "../src/features/league/llmopt/copy";
import { mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks } from "./leagueMocks";
import { holdModel, routeChat } from "./llmoptChat";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const PAGE = `/league/${EXAMPLE_CLAIM.leagueId}/members/${EXAMPLE_CLAIM.entryId}/llmopt`;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, authorization, idempotency-key",
};

function answer(route: Route, json: unknown) {
  return route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: CORS })
    : route.fulfill({ json, headers: CORS });
}

async function open(page: Page, language: "en" | "tr") {
  await installLeagueMocks(page);
  await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
  const squad = mockEntrySquadEnvelopes[EXAMPLE_CLAIM.entryId]!.payload;
  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, {
      season: squad.season,
      players: [
        { id: 990001, name: "Norberto Bercique Gomes Betuncal", team: "Nottingham Forest" },
      ],
    }),
  );
  await page.goto(PAGE);
  await expect(page.getByRole("heading", { level: 1, name: "LLMOPT" })).toBeVisible();
}

async function listPosition(list: Locator) {
  return list.evaluate((element) => ({
    top: element.scrollTop,
    remaining: element.scrollHeight - element.scrollTop - element.clientHeight,
  }));
}

for (const language of ["en", "tr"] as const) {
  test(`the ${language} rule controls fit their labels on narrow phones`, async ({ page }) => {
    await open(page, language);
    const copy = LLMOPT_COPY[language];
    for (const width of [320, 360, 390]) {
      await page.setViewportSize({ width, height: 844 });
      for (const kind of ["hold_transfers", "include_player", "hit_budget"]) {
        await page.getByRole("combobox", { name: copy.rule, exact: true }).selectOption(kind);
        await page.getByRole("combobox", { name: copy.strength, exact: true }).selectOption("soft");
        const outside = await page
          .locator("main label select, main label input")
          .evaluateAll((controls) =>
            controls.flatMap((control) => {
              const bounds = control.getBoundingClientRect();
              const label = control.closest("label")!.getBoundingClientRect();
              return bounds.left < label.left - 1 || bounds.right > label.right + 1
                ? [
                    {
                      text: control.closest("label")!.textContent,
                      right: bounds.right,
                      label: label.right,
                    },
                  ]
                : [];
            }),
          );
        expect(outside, `${width}px ${kind}`).toEqual([]);
      }
    }
  });

  for (const reducedMotion of ["no-preference", "reduce"] as const) {
    test(`the ${language} phone chat follows replies and keeps keyboard focus (${reducedMotion})`, async ({
      page,
    }) => {
      test.skip(!API, "API build required");
      await page.setViewportSize({ width: 390, height: 844 });
      await page.emulateMedia({ reducedMotion });
      await open(page, language);
      const copy = LLMOPT_COPY[language];
      let question = 0;
      let release: (() => void) | undefined;
      let pending: Promise<void> | undefined;
      await routeChat(page, API, async (route) => {
        if (route.request().method() === "POST") {
          await pending;
          question += 1;
        }
        return answer(route, {
          status: "clarification",
          message: `Question ${question}: please specify the club and the preferred week for this player to join your squad.`,
        });
      });
      await holdModel(page);
      const input = page.getByRole("textbox", { name: copy.chat });
      const send = page.getByRole("button", { name: copy.send, exact: true });
      const conversation = page.locator("main ol[aria-live]");
      async function sendWithKeyboard(number: number) {
        await input.fill(`Request ${number}: buy a striker next week.`);
        await input.press("Tab");
        await expect(send).toBeFocused();
        await send.press("Enter");
      }

      for (let number = 1; number <= 5; number++) {
        await sendWithKeyboard(number);
        await expect(input).toBeEnabled();
        await expect(input).toHaveValue("");
        await expect(input).toBeFocused();
        await expect.poll(async () => (await listPosition(conversation)).remaining).toBeLessThan(1);
      }

      // A reader who scrolls back keeps that position when another answer arrives.
      await conversation.evaluate((list) => {
        list.scrollTop = 0;
        list.dispatchEvent(new Event("scroll"));
      });
      await expect.poll(async () => (await listPosition(conversation)).top).toBe(0);
      await sendWithKeyboard(6);
      await expect(input).toBeFocused();
      expect((await listPosition(conversation)).top).toBe(0);
      expect((await listPosition(conversation)).remaining).toBeGreaterThan(100);

      // Moving focus outside the chat during a slow answer takes priority over its return.
      pending = new Promise<void>((resolve) => (release = resolve));
      await sendWithKeyboard(7);
      await expect(input).toBeDisabled();
      const rule = page.getByRole("combobox", { name: copy.rule, exact: true });
      await rule.focus();
      release!();
      await expect(input).toBeEnabled();
      await expect(rule).toBeFocused();

      // Reloaded clarification context starts at its beginning, without scrolling the page.
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.reload();
      await expect(conversation).toBeVisible();
      expect((await listPosition(conversation)).top).toBe(0);
      expect(await page.evaluate(() => window.scrollY)).toBe(0);
    });
  }
}
