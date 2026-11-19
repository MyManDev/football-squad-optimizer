// @vitest-environment node
import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { PROVIDERS, checkedProviderCall, providerRequest } from "./providers";
import type { OwnKeyProvider } from "./ownKey";

const schema = JSON.parse(
  readFileSync(
    new URL("../../../../../docs/contracts/llmopt_intent_v1.schema.json", import.meta.url),
    "utf8",
  ),
);
const call = checkedProviderCall({
  system: "Translate preference rules only.",
  user: "{}",
  schema,
  schema_name: "llmopt_intent_v1",
  max_output_tokens: 1200,
});

it.each(Object.keys(PROVIDERS) as OwnKeyProvider[])(
  "carries the actual typed priority contract through %s",
  (provider) => {
    const request = providerRequest(
      {
        provider,
        model: "fixture",
        key: "fixture-secret",
        ...(provider === "local" ? { baseUrl: "http://127.0.0.1:1234/v1" } : {}),
      },
      call,
    );
    const body = JSON.stringify(request.body);
    expect(body).toContain("max_total_cost_tenths");
    expect(body).toContain("priority");
    expect(body).not.toContain("fixture-secret");
    if (PROVIDERS[provider].output === "json_schema")
      expect(request.body.response_format).toMatchObject({
        type: "json_schema",
        json_schema: { strict: true, schema },
      });
    else if (PROVIDERS[provider].output === "tool")
      expect(request.body.tools).toEqual([{ name: "llmopt_intent_v1", input_schema: schema }]);
    else
      expect((request.body.messages as { content: string }[])[0]!.content).toContain(
        JSON.stringify(schema),
      );
    function visit(node: unknown) {
      if (!node || typeof node !== "object") return;
      if (Array.isArray(node)) {
        node.forEach(visit);
        return;
      }
      const value = node as Record<string, unknown>;
      if (value.properties)
        for (const field of Object.values(
          value.properties as Record<string, Record<string, unknown>>,
        ))
          expect(field).toHaveProperty("type");
      Object.values(value).forEach(visit);
    }
    visit(schema);
  },
);
