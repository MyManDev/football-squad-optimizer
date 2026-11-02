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

it("keeps participation evidence optional and refuses audit internals and invalid counts", () => {
  const payload = mockEntryAdviceEnvelope(101, "saf-puan", 3).payload;
  const evidence = {
    version: "football_participation_evidence_v1",
    as_of: "2026-09-01T00:00:00Z",
    gameweek: 6,
    applied_player_count: 2,
    unapplied_statement_count: 1,
    captured_percentage_count: 5,
    manager_statement_count: 3,
    assumptions: ["source_eligibility_only", "no_start_or_minutes_reestimate"],
  };
  const outcome = {
    player_id: 1,
    disposition: "stated_expected_absent",
    applied: true,
    reason: "explicit_evidence",
    source_url: "https://www.liverpoolfc.com/news/team-update",
    source_published_at: evidence.as_of,
  };
  expect(isAdvicePayload(payload)).toBe(true);
  expect(isAdvicePayload({ ...payload, participation_evidence: evidence })).toBe(true);
  expect(
    isAdvicePayload({
      ...payload,
      participation_evidence: { ...evidence, statement_outcomes: [outcome] },
    }),
  ).toBe(true);
  for (const participation_evidence of [
    { ...evidence, applied_player_count: -1 },
    { ...evidence, base_revision: "internal" },
    { ...evidence, statement_outcomes: [{ ...outcome, raw_quote: "private" }] },
  ]) {
    expect(isAdvicePayload({ ...payload, participation_evidence })).toBe(false);
  }
});

it("refuses malformed preference metadata instead of accepting an unverified plan", () => {
  const payload = mockEntryAdviceEnvelope(101, "saf-puan", 3).payload;
  expect(isAdvicePayload({ ...payload, preferences: { keep_players: [101], no_hits: true } })).toBe(
    true,
  );
  for (const preferences of [
    null,
    { no_hits: "true" },
    { keep_players: [101], avoid_players: [101] },
    { hidden: true },
  ]) {
    expect(isAdvicePayload({ ...payload, preferences })).toBe(false);
  }
  expect(isAdvicePayload({ ...payload, preferences_scope: "first_week" })).toBe(false);
  expect(isAdvicePayload({ ...payload, selection_top100_weight: 99 })).toBe(false);
});
