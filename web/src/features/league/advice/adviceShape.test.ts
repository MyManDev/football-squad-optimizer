/// <reference types="node" />
// @vitest-environment node
import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { isAdvicePayload } from "./adviceShape";

/** The committed contract the Python publisher generates and this shape mirrors by hand. */
const schema = JSON.parse(
  readFileSync(
    new URL("../../../../../docs/contracts/advice_read_v1.schema.json", import.meta.url),
    "utf-8",
  ),
) as { properties: { payload: { properties: Record<string, unknown>; required: string[] } } };

/**
 * Ask the shape which payload keys it checks, without exporting its tables: a valid
 * payload behind a Proxy that notes every key read (a required key) and every key
 * probed with `in` first (an optional key). The shape must accept the payload, or its
 * short-circuit would stop the walk before the last key.
 */
function checkedKeys(): { required: Set<string>; optional: Set<string> } {
  const required = new Set<string>();
  const optional = new Set<string>();
  const payload: object = mockEntryAdviceEnvelope(101, "saf-puan", 3).payload;
  const probe = new Proxy(payload, {
    has(target, key) {
      if (typeof key === "string") optional.add(key);
      return Reflect.has(target, key);
    },
    get(target, key) {
      if (typeof key === "string" && !optional.has(key)) required.add(key);
      return Reflect.get(target, key);
    },
  });
  expect(isAdvicePayload(probe)).toBe(true);
  return { required, optional };
}

it("requires exactly the payload keys the served schema requires", () => {
  const { required } = checkedKeys();
  expect([...required].sort()).toEqual([...schema.properties.payload.required].sort());
});

it("checks exactly the payload keys the served schema declares", () => {
  const { required, optional } = checkedKeys();
  expect([...required, ...optional].sort()).toEqual(
    Object.keys(schema.properties.payload.properties).sort(),
  );
});
