import { expect, test } from "@playwright/test";

import { LLMOPT_COPY } from "../src/features/league/llmopt/copy";
import { MAX_MESSAGE_LENGTH } from "../src/features/league/llmopt/intent";
import { mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks } from "./leagueMocks";
import { holdModel, routeChat } from "./llmoptChat";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const { leagueId, entryId } = EXAMPLE_CLAIM;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,authorization",
};

for (const language of ["en", "tr"] as const) {
  test(`a full clarification context preserves the answer and offers a fresh shorter request (${language})`, async ({
    page,
  }) => {
    test.skip(!API, "API build required");
    await installLeagueMocks(page);
    await page.addInitScript(
      (language) => localStorage.setItem("squadopt.language", language),
      language,
    );
    const copy = LLMOPT_COPY[language];
    const squad = mockEntrySquadEnvelopes[entryId]!.payload;
    await page.route(`${API}/api/v1/contributions/players`, (route) =>
      route.fulfill({
        headers: CORS,
        json: {
          season: squad.season,
          players: [...squad.starting_xi, ...squad.bench].map(({ player_id, name, team }) => ({
            id: player_id,
            name,
            team,
          })),
        },
      }),
    );
    let calls = 0;
    await routeChat(page, API, async (route) => {
      if (route.request().method() === "OPTIONS")
        return route.fulfill({ status: 204, headers: CORS });
      calls++;
      const request = route.request().postDataJSON();
      if (calls === 3) expect(request.clarification).toBeUndefined();
      return route.fulfill({
        headers: CORS,
        json:
          calls < 3
            ? { status: "clarification", message: "Which week?" }
            : { status: "draft", draft: { hard: [{ kind: "no_hits" }], soft: [] } },
      });
    });
    await page.goto(`/league/${leagueId}/members/${entryId}/llmopt`);
    await holdModel(page);
    const input = page.getByRole("textbox", { name: copy.chat });
    const send = page.getByRole("button", { name: copy.send, exact: true });
    await input.fill("Buy a striker.".padEnd(MAX_MESSAGE_LENGTH, "."));
    await send.click();
    await expect(page.getByText("Which week?", { exact: true })).toBeVisible();
    await input.fill("Next week.");
    await send.click();
    await expect(page.getByText(copy.conversationTooLong)).toBeVisible();
    await expect(input).toHaveValue("Next week.");
    await expect(page.getByRole("button", { name: copy.compute, exact: true })).toBeDisabled();
    expect(calls).toBe(2);
    await page.getByRole("button", { name: copy.dismissQuestion }).click();
    await input.fill("Buy a striker next week. No hits.");
    await send.click();
    await expect(
      page.getByRole("button", { name: `${copy.remove} · ${copy.rules.no_hits}`, exact: true }),
    ).toBeVisible();
    await expect(input).toHaveValue("");
    await expect(page.getByRole("button", { name: copy.compute, exact: true })).toBeEnabled();
    expect(calls).toBe(3);
  });
}
