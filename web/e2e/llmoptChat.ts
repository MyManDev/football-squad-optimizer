import type { Page, Route } from "@playwright/test";

import { LLMOPT_COPY } from "../src/features/league/llmopt/copy";

/** The provider the test key is saved for; the page sends the model call there. */
export const TEST_PROVIDER = "https://api.openai.com/v1/chat/completions";
/** A made-up key. It is only ever sent to the stubbed provider. */
export const TEST_KEY = "sk-test-e2e-chat-0001";

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, authorization, idempotency-key",
};

function fulfil(route: Route, json: unknown) {
  return route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: CORS })
    : route.fulfill({ json, headers: CORS });
}

/**
 * The same route, with the request body read as the intent request the page had checked.
 * `/check` gets `{ request, reply }`; a spec's handler reads the member's message and draft.
 */
function asIntentRoute(route: Route): Route {
  const request = route.request();
  const intentRequest = new Proxy(request, {
    get(target, property) {
      if (property === "postDataJSON")
        return () => (target.postDataJSON() as { request?: unknown } | null)?.request ?? null;
      const value: unknown = Reflect.get(target, property, target);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
  return new Proxy(route, {
    get(target, property) {
      if (property === "request") return () => intentRequest;
      const value: unknown = Reflect.get(target, property, target);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}

/**
 * Stands in for the member's model. The page asks the site for the prompt, sends it to the
 * provider and has the reply checked; `check` answers that last step, as the site's check
 * would, and reads the intent request from `route.request().postDataJSON()`.
 */
export async function routeChat(
  page: Page,
  api: string | undefined,
  check: (route: Route) => unknown,
) {
  await page.route(`${api}/api/v1/llmopt/prompt`, (route) =>
    fulfil(route, {
      system: "Read the member's instructions.",
      user: "{}",
      schema: { type: "object" },
      schema_name: "llmopt_intent",
      max_output_tokens: 1200,
    }),
  );
  await page.route(TEST_PROVIDER, (route) =>
    fulfil(route, {
      choices: [{ finish_reason: "stop", message: { content: '{"status":"draft"}' } }],
    }),
  );
  await page.route(`${api}/api/v1/llmopt/check`, (route) => check(asIntentRoute(route)));
}

/**
 * Saves the test key in the page's form, which turns the chat on. The key lives only in the
 * tab's memory, so a spec calls this again after every load of the page.
 */
export async function holdModel(page: Page) {
  const language = await page.evaluate(() => localStorage.getItem("squadopt.language"));
  const words = LLMOPT_COPY[language === "tr" ? "tr" : "en"].ownKey;
  const main = page.getByRole("main");
  await main.getByLabel(words.provider, { exact: true }).selectOption("openai");
  await main.getByRole("textbox", { name: words.model }).fill("gpt-5-mini");
  await main.getByLabel(words.key, { exact: true }).fill(TEST_KEY);
  await main.getByRole("button", { name: words.save }).click();
}
