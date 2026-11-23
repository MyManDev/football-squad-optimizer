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
  system: "Translate decisions only.",
  user: "{}",
  schema,
  schema_name: "llmopt_intent_v1",
  max_output_tokens: 1200,
});

it.each(Object.keys(PROVIDERS) as OwnKeyProvider[])(
  "carries the complete typed plan schema through %s without an outcome or key",
  (provider) => {
    const request = providerRequest(
      {
        provider,
        model: "test-model",
        key: "test-secret",
        ...(provider === "local" ? { baseUrl: "http://127.0.0.1:1234/v1" } : {}),
      },
      call,
    );
    const body = JSON.stringify(request.body);
    expect(body).toContain("plan_command");
    expect(body).not.toContain("test-secret");
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
    const command = schema.properties.plan_command.anyOf[0];
    expect(command.properties.plan_label).toEqual({
      type: "string",
      enum: Array.from({ length: 12 }, (_, i) => `P${i + 1}`),
    });
    expect(command.properties).not.toHaveProperty("plan_id");
    const visit = (node: Record<string, unknown>) => {
      if (Array.isArray(node.anyOf)) {
        expect(Object.keys(node)).toEqual(["anyOf"]);
        expect(node.anyOf.length).toBeGreaterThan(0);
        node.anyOf.forEach(visit);
        return;
      }
      expect(node).toHaveProperty("type");
      if (node.properties)
        Object.values(node.properties as Record<string, Record<string, unknown>>).forEach(visit);
      if (node.items) visit(node.items as Record<string, unknown>);
    };
    visit(schema);
  },
);
