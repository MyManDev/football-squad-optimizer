/**
 * The manager's word is a switch on the one-week pure-points plan and nothing else. The
 * index says whether the producer solved it; the URL says whether the member asked; the
 * selection honours the ask only where both hold, and otherwise reports why not rather
 * than pointing at a document nobody solved.
 */

import { describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import type { EntryAdviceIndex } from "../types";
import { resolvePublishedAdvice } from "./adviceSelection";

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const ENTRY = 35249001;
const LEAGUE = mockEntryAdviceIndex(ENTRY).payload.league_id;

const SOLVED: EntryAdviceIndex["evidence"] = {
  available: true,
  path: `advice/${ENTRY}/saf-puan/1/hoca-sozu.json`,
  applied_count: 1,
  source_kind: "synthetic_fixture",
  source_label: "club_news_v1.fixture.json",
  clubs_covered: ["Arsenal"],
  rule_version: "managers_word_rule_v1",
};

function resolve(query: string, evidence: EntryAdviceIndex["evidence"]) {
  const index = { ...mockEntryAdviceIndex(ENTRY).payload, evidence };
  return resolvePublishedAdvice(new URLSearchParams(query), LEAGUE, ENTRY, MEMBERS, index);
}

describe("the manager's word switch", () => {
  it("is off and unavailable when the publish read no club news, with the reason", () => {
    const selection = resolve("mode=saf-puan&window=1&llm=on", {
      available: false,
      reason: "no_evidence_this_run",
    });
    expect(selection.status).toBe("ready");
    expect(selection.path).toBe(`advice/${ENTRY}/saf-puan/1.json`);
    expect(selection.evidence).toEqual({
      available: false,
      on: false,
      reason: "no_evidence_this_run",
      sourceKind: null,
      appliedCount: null,
    });
  });

  it("is available but off until the URL asks, and then points at the solved document", () => {
    const off = resolve("mode=saf-puan&window=1", SOLVED);
    expect(off.path).toBe(`advice/${ENTRY}/saf-puan/1.json`);
    expect(off.evidence).toMatchObject({
      available: true,
      on: false,
      sourceKind: "synthetic_fixture",
    });

    const on = resolve("mode=saf-puan&window=1&llm=on", SOLVED);
    expect(on.status).toBe("ready");
    expect(on.path).toBe(SOLVED && SOLVED.available ? SOLVED.path : null);
    expect(on.evidence).toMatchObject({ available: true, on: true, appliedCount: 1 });
  });

  it("stays off on a longer window and on a rival strategy, without hiding the availability", () => {
    const window = resolve("mode=saf-puan&window=3&llm=on", SOLVED);
    expect(window.path).toBe(`advice/${ENTRY}/saf-puan/3.json`);
    expect(window.evidence).toMatchObject({ available: true, on: false });

    const rival = resolve("mode=ortak-koru&window=1&llm=on", SOLVED);
    expect(rival.status).toBe("ready");
    expect(rival.path).not.toContain("hoca-sozu");
    expect(rival.evidence).toMatchObject({ available: true, on: false });
  });

  it("treats an index from before the word existed as no word", () => {
    const index = mockEntryAdviceIndex(ENTRY).payload;
    delete (index as { evidence?: unknown }).evidence;
    const selection = resolvePublishedAdvice(
      new URLSearchParams("mode=saf-puan&window=1&llm=on"),
      LEAGUE,
      ENTRY,
      MEMBERS,
      index,
    );
    expect(selection.path).toBe(`advice/${ENTRY}/saf-puan/1.json`);
    expect(selection.evidence).toMatchObject({ available: false, on: false, reason: null });
  });
});
