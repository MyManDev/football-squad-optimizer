/**
 * The chip in the URL, and what the selection makes of it: a chip is read only where the
 * index names its file for this member, on the plain one-week pure-points plan, with the
 * manager's word off and the Top 100 influence at 0. Anything else shows the plan without
 * a chip and says so.
 */

import { describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import type { EntryAdviceIndex } from "../types";
import { resolvePublishedAdvice } from "./adviceSelection";
import { chipPath, parseChip } from "./chipChoice";
import { TOP100_WEIGHTS, top100Path } from "./top100";

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const ENTRY = 35249001;
const LEAGUE = mockEntryAdviceIndex(ENTRY).payload.league_id;

const SOLVED: EntryAdviceIndex["chips"] = {
  available: true,
  paths: {
    wildcard: chipPath(ENTRY, "wildcard"),
    bboost: chipPath(ENTRY, "bboost"),
    "3xc": chipPath(ENTRY, "3xc"),
  },
  unavailable: [{ chip: "freehit", reason: "already_played" }],
  held: ["wildcard", "bboost", "3xc"],
};

function index(chips: EntryAdviceIndex["chips"]): EntryAdviceIndex {
  const weights = TOP100_WEIGHTS.filter((weight) => weight !== 0);
  return {
    ...mockEntryAdviceIndex(ENTRY).payload,
    chips,
    evidence: {
      available: true,
      path: `advice/${ENTRY}/saf-puan/1/hoca-sozu.json`,
      applied_count: 1,
      source_kind: "synthetic_fixture",
      source_label: "club_news_v1.fixture.json",
      clubs_covered: [],
      rule_version: "managers_word_rule_v1",
    },
    top100: {
      available: true,
      published_weight: 0,
      weights: [...TOP100_WEIGHTS],
      paths: Object.fromEntries(weights.map((w) => [String(w), top100Path(ENTRY, w, false)])),
      word_paths: {},
      unavailable: [],
    },
  };
}

function resolve(query: string, chips: EntryAdviceIndex["chips"] = SOLVED) {
  return resolvePublishedAdvice(new URLSearchParams(query), LEAGUE, ENTRY, MEMBERS, index(chips));
}

describe("parseChip", () => {
  it.each([
    [null, null, true],
    ["wildcard", "wildcard", true],
    ["freehit", "freehit", true],
    ["bboost", "bboost", true],
    ["3xc", "3xc", true],
    ["", null, false],
    ["Wildcard", null, false],
    ["triple", null, false],
    ["none", null, false],
    ["../index", null, false],
  ])("reads %s as %s (known: %s)", (raw, chip, known) => {
    const params = new URLSearchParams(raw === null ? "" : `chip=${encodeURIComponent(raw)}`);
    expect(parseChip(params)).toEqual({ chip, known });
  });
});

describe("the chip selection", () => {
  it("reads the chip's file on the plain one-week pure-points plan", () => {
    const selection = resolve("mode=saf-puan&window=1&chip=bboost");
    expect(selection.status).toBe("ready");
    expect(selection.path).toBe(`advice/${ENTRY}/saf-puan/1/chip-bboost.json`);
    expect(selection.chip).toMatchObject({ available: true, chip: "bboost", notOffered: false });
    expect(selection.chip.options).toEqual(["wildcard", "bboost", "3xc"]);
    expect(selection.chip.held).toEqual(["wildcard", "bboost", "3xc"]);
    expect(selection.chip.reasons).toEqual({ freehit: "already_played" });
  });

  it("reads the published plan when no chip is asked for", () => {
    const selection = resolve("mode=saf-puan&window=1");
    expect(selection.path).toBe(`advice/${ENTRY}/saf-puan/1.json`);
    expect(selection.chip.chip).toBeNull();
    expect(selection.chip.notOffered).toBe(false);
  });

  it("leaves the chip out while the manager's word or a Top 100 setting is on", () => {
    const word = resolve("mode=saf-puan&window=1&chip=bboost&llm=on");
    expect(word.path).toBe(`advice/${ENTRY}/saf-puan/1/hoca-sozu.json`);
    expect(word.chip.chip).toBeNull();
    expect(word.chip.notOffered).toBe(false);

    const weighted = resolve("mode=saf-puan&window=1&chip=bboost&top100=20");
    expect(weighted.path).toBe(`advice/${ENTRY}/saf-puan/1/top100-20.json`);
    expect(weighted.chip.chip).toBeNull();
    expect(weighted.top100.weight).toBe(20);
  });

  it("never swaps the path on a longer window or a rival strategy", () => {
    const window = resolve("mode=saf-puan&window=3&chip=bboost");
    expect(window.path).toBe(`advice/${ENTRY}/saf-puan/3.json`);
    expect(window.chip.chip).toBeNull();

    const rival = resolve("mode=ortak-koru&window=1&chip=bboost");
    expect(rival.path ?? "").not.toContain("chip-");
    expect(rival.chip.chip).toBeNull();
  });

  it("shows the plan without a chip for one the member cannot be shown, and says so", () => {
    for (const asked of ["freehit", "limitless", ""]) {
      const selection = resolve(`mode=saf-puan&window=1&chip=${asked}`);
      expect(selection.path).toBe(`advice/${ENTRY}/saf-puan/1.json`);
      expect(selection.chip.chip).toBeNull();
      expect(selection.chip.notOffered).toBe(true);
    }
  });

  it("honours a chip only at the one path a chip document may live at", () => {
    const elsewhere = resolve("mode=saf-puan&window=1&chip=wildcard", {
      ...SOLVED!,
      paths: {
        wildcard: `advice/${ENTRY}/saf-puan/1.json`,
        bboost: `advice/202/saf-puan/1/chip-bboost.json`,
        "3xc": `advice/${ENTRY}/saf-puan/1/../index.json`,
      },
    } as EntryAdviceIndex["chips"]);
    expect(elsewhere.chip.options).toEqual([]);
    expect(elsewhere.chip.available).toBe(false);
    expect(elsewhere.path).toBe(`advice/${ENTRY}/saf-puan/1.json`);
  });

  it("carries the producer's reason when no chip was solved, and none without a block", () => {
    const unknown = resolve("mode=saf-puan&window=1&chip=wildcard", {
      available: false,
      reason: "chip_history_unknown",
    });
    expect(unknown.chip).toMatchObject({
      available: false,
      chip: null,
      notOffered: true,
      reason: "chip_history_unknown",
    });
    // An index from before the chips existed carries no block at all.
    const before = resolvePublishedAdvice(
      new URLSearchParams("mode=saf-puan&window=1"),
      LEAGUE,
      ENTRY,
      MEMBERS,
      index(undefined),
    );
    expect(before.chip).toMatchObject({ available: false, reason: null, options: [] });
    expect(before.path).toBe(`advice/${ENTRY}/saf-puan/1.json`);
  });
});
