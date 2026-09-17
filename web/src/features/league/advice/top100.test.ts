/**
 * The Top 100 setting in the URL, and what the selection makes of it: a weight is read
 * only where the index names its file for this member, on the one-week pure-points plan,
 * with the manager's word as the URL has it. Anything else shows the plan at 0 and says so.
 */

import { describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import type { EntryAdviceIndex } from "../types";
import { resolvePublishedAdvice } from "./adviceSelection";
import { TOP100_WEIGHTS, parseTop100, top100Path } from "./top100";

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const ENTRY = 35249001;
const LEAGUE = mockEntryAdviceIndex(ENTRY).payload.league_id;

function menu(overrides: Partial<Extract<EntryAdviceIndex["top100"], { available: true }>> = {}) {
  const weights = TOP100_WEIGHTS.filter((weight) => weight !== 0);
  return {
    available: true as const,
    published_weight: 0,
    weights: [...TOP100_WEIGHTS],
    paths: Object.fromEntries(weights.map((w) => [String(w), top100Path(ENTRY, w, false)])),
    word_paths: Object.fromEntries(weights.map((w) => [String(w), top100Path(ENTRY, w, true)])),
    unavailable: [],
    ...overrides,
  };
}

function index(top100: EntryAdviceIndex["top100"], evidence = true): EntryAdviceIndex {
  return {
    ...mockEntryAdviceIndex(ENTRY).payload,
    top100,
    evidence: evidence
      ? {
          available: true,
          path: `advice/${ENTRY}/saf-puan/1/hoca-sozu.json`,
          applied_count: 1,
          source_kind: "synthetic_fixture",
          source_label: "club_news_v1.fixture.json",
          clubs_covered: [],
          rule_version: "managers_word_rule_v1",
        }
      : { available: false, reason: "no_evidence_this_run" },
  };
}

function resolve(query: string, top100: EntryAdviceIndex["top100"], evidence = true) {
  return resolvePublishedAdvice(
    new URLSearchParams(query),
    LEAGUE,
    ENTRY,
    MEMBERS,
    index(top100, evidence),
  );
}

describe("parseTop100", () => {
  it.each([
    [null, 0, true],
    ["0", 0, true],
    ["5", 5, true],
    ["50", 50, true],
    ["", 0, false],
    ["15", 0, false],
    ["50.0", 0, false],
    ["05", 0, false],
    ["abc", 0, false],
    ["-5", 0, false],
    ["100", 0, false],
  ])("reads %s as %s (offered: %s)", (raw, weight, offered) => {
    const params = new URLSearchParams(raw === null ? "" : `top100=${raw}`);
    expect(parseTop100(params)).toEqual({ weight, offered });
  });
});

describe("the Top 100 selection", () => {
  it("reads the weighted file on the one-week pure-points plan", () => {
    const selection = resolve("mode=saf-puan&window=1&top100=20", menu());
    expect(selection.status).toBe("ready");
    expect(selection.path).toBe(`advice/${ENTRY}/saf-puan/1/top100-20.json`);
    expect(selection.top100).toMatchObject({ available: true, weight: 20, notOffered: false });
    expect(selection.top100.weights).toEqual([...TOP100_WEIGHTS]);
    expect(selection.evidence.on).toBe(false);
  });

  it("reads the weighted file with the word when both are on", () => {
    const selection = resolve("mode=saf-puan&window=1&top100=20&llm=on", menu());
    expect(selection.path).toBe(`advice/${ENTRY}/saf-puan/1/top100-20-hoca-sozu.json`);
    expect(selection.evidence.on).toBe(true);
    expect(selection.top100.weight).toBe(20);
  });

  it("reads the published plan at 0, and the word's plan at 0 with the word", () => {
    expect(resolve("mode=saf-puan&window=1", menu()).path).toBe(`advice/${ENTRY}/saf-puan/1.json`);
    expect(resolve("mode=saf-puan&window=1&top100=0&llm=on", menu()).path).toBe(
      `advice/${ENTRY}/saf-puan/1/hoca-sozu.json`,
    );
  });

  it("never swaps the path on a longer window or a rival strategy", () => {
    const window = resolve("mode=saf-puan&window=3&top100=20", menu());
    expect(window.path).toBe(`advice/${ENTRY}/saf-puan/3.json`);
    expect(window.top100.weight).toBe(0);
    expect(window.top100.weights).toEqual([0]);
    expect(window.top100.notOffered).toBe(true);

    const rival = resolve("mode=ortak-koru&window=1&top100=20", menu());
    expect(rival.path ?? "").not.toContain("top100");
    expect(rival.top100.weight).toBe(0);
  });

  it("shows a weight without its file as unavailable, and the plan at 0 in its place", () => {
    const partial = menu({
      paths: { "5": top100Path(ENTRY, 5, false) },
      word_paths: {},
      unavailable: [{ weight: 20, word: false, reason: "not_solved_for_member" }],
    });
    const plain = resolve("mode=saf-puan&window=1&top100=20", partial);
    expect(plain.top100.weights).toEqual([0, 5]);
    expect(plain.top100.weight).toBe(0);
    expect(plain.top100.notOffered).toBe(true);
    expect(plain.path).toBe(`advice/${ENTRY}/saf-puan/1.json`);

    const word = resolve("mode=saf-puan&window=1&top100=5&llm=on", partial);
    expect(word.top100.weights).toEqual([0]);
    expect(word.top100.weight).toBe(0);
    // Solved without the word, so offered; the controls name the switches instead.
    expect(word.top100.notOffered).toBe(false);
    expect(word.path).toBe(`advice/${ENTRY}/saf-puan/1/hoca-sozu.json`);
  });

  it("ignores an index path that is not the member's own file", () => {
    const foreign = menu({ paths: { "20": "advice/999/saf-puan/1/top100-20.json" } });
    const selection = resolve("mode=saf-puan&window=1&top100=20", foreign);
    expect(selection.top100.weights).not.toContain(20);
    expect(selection.path).toBe(`advice/${ENTRY}/saf-puan/1.json`);
  });

  it("carries the producer's reason when no weight was solved", () => {
    const selection = resolve("mode=saf-puan&window=1&top100=20", {
      available: false,
      reason: "top100_inputs_refused",
    });
    expect(selection.top100).toMatchObject({
      available: false,
      weight: 0,
      reason: "top100_inputs_refused",
    });
    expect(selection.path).toBe(`advice/${ENTRY}/saf-puan/1.json`);
  });

  it("treats an index from before the menu as no menu", () => {
    const selection = resolve("mode=saf-puan&window=1&top100=20", undefined);
    expect(selection.top100.available).toBe(false);
    expect(selection.top100.reason).toBeNull();
    expect(selection.path).toBe(`advice/${ENTRY}/saf-puan/1.json`);
  });

  it("reports a value the menu does not offer", () => {
    const selection = resolve("mode=saf-puan&window=1&top100=15", menu());
    expect(selection.top100.notOffered).toBe(true);
    expect(selection.top100.weight).toBe(0);
  });
});
