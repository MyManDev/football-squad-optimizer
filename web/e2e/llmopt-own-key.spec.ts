import { expect, test, type Route } from "@playwright/test";

import { LLMOPT_COPY } from "../src/features/league/llmopt/copy";
import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks } from "./leagueMocks";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
const ENTRY = EXAMPLE_CLAIM.entryId;
const PAGE = `/league/${LEAGUE}/members/${ENTRY}/llmopt`;
const PROVIDER = "https://api.openai.com/v1/chat/completions";
const KEY = "sk-test-e2e-own-key-0001";
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, authorization, idempotency-key",
};
const en = LLMOPT_COPY.en;

function answer(route: Route, json: unknown) {
  return route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: CORS })
    : route.fulfill({ json, headers: CORS });
}

test("a member's own key reads the chat at the provider, never reaches the site, and Delete deletes it", async ({
  page,
}) => {
  test.skip(!API, "API build required");
  await page.setViewportSize({ width: 390, height: 844 });
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const players = [...squad.starting_xi, ...squad.bench].map((player) => ({
    id: player.player_id,
    name: player.name,
    team: player.team,
  }));
  const carried: string[] = [];
  page.on("request", async (request) => {
    const headers = Object.entries(await request.allHeaders()).flat();
    if ([request.url(), request.postData() ?? "", ...headers].some((part) => part.includes(KEY)))
      carried.push(`${request.method()} ${request.url()}`);
  });
  const provided: Record<string, string>[] = [];
  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, { season: squad.season, players }),
  );
  await page.route(`${API}/api/v1/llmopt/intent`, (route) =>
    route.fulfill({ status: 500, headers: CORS }),
  );
  await page.route(`${API}/api/v1/llmopt/prompt`, (route) =>
    answer(route, {
      system: "Read the member's instructions.",
      user: "{}",
      schema: { type: "object" },
      schema_name: "llmopt_intent",
      max_output_tokens: 1200,
    }),
  );
  await page.route(`${API}/api/v1/llmopt/check`, async (route) => {
    if (route.request().method() === "POST")
      expect(route.request().postDataJSON()).toMatchObject({ reply: '{"status":"draft"}' });
    await answer(route, { status: "draft", draft: { hard: [{ kind: "no_hits" }], soft: [] } });
  });
  await page.route(PROVIDER, async (route) => {
    if (route.request().method() === "POST") provided.push(await route.request().allHeaders());
    await answer(route, {
      choices: [{ finish_reason: "stop", message: { content: '{"status":"draft"}' } }],
    });
  });

  await page.goto(PAGE);
  const main = page.getByRole("main");
  const keyField = main.getByLabel(en.ownKey.key, { exact: true });
  await main.getByLabel(en.ownKey.provider, { exact: true }).selectOption("openai");
  await main.getByRole("textbox", { name: en.ownKey.model }).fill("gpt-5-mini");
  await keyField.fill(KEY);
  const save = main.getByRole("button", { name: en.ownKey.save });
  expect((await save.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await save.click();
  const held = main.getByRole("group", { name: en.ownKey.title });
  await expect(held).toContainText("OpenAI");
  await expect(held).toContainText("gpt-5-mini");
  await expect(keyField).toHaveCount(0);

  await main.getByRole("textbox", { name: en.chat }).fill("No hits.");
  await main.getByRole("button", { name: en.send, exact: true }).click();
  await expect(
    main.getByRole("button", { name: `${en.remove} · ${en.rules.no_hits}` }),
  ).toBeVisible();
  expect(provided).toHaveLength(1);
  expect(provided[0]!.authorization).toBe(`Bearer ${KEY}`);

  const remove = main.getByRole("button", { name: en.ownKey.delete });
  expect((await remove.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await remove.click();
  await expect(keyField).toHaveValue("");
  await expect(main.getByText("gpt-5-mini", { exact: true })).toHaveCount(0);

  const stored = await page.evaluate(async () => {
    const storage = (store: Storage) =>
      Array.from({ length: store.length }, (_, index) => {
        const name = store.key(index) ?? "";
        return `${name}=${store.getItem(name)}`;
      });
    const databases = (await indexedDB.databases()).map(({ name }) => name ?? "");
    return [
      ...storage(localStorage),
      ...storage(sessionStorage),
      document.cookie,
      location.href,
      ...databases,
    ].join("\n");
  });
  expect(stored).not.toContain(KEY);
  expect(carried).toEqual([`POST ${PROVIDER}`]);
  // No page width scroll at phone width.
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
