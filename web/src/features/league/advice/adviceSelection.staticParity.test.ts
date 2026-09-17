/// <reference types="node" />
// @vitest-environment node
/**
 * With no compute service, the resolver answers exactly as it did before it learned about one.
 *
 * `adviceSelection.staticParity.json` was recorded from the resolver as it stood before the
 * `computable` facet existed: every index the selection tests build (the example publish,
 * the manager's word solved, the Top 100 menu with its per-plan documents, the chips, an
 * empty publish, a wrong member, no index at all) against every kind of link those tests
 * ask for. A static build passes no capabilities, so its selection objects must still be
 * those, key for key. The file keeps a SHA-256 of each selection's JSON (the objects
 * themselves run to several hundred kilobytes); a mismatch prints the selection that
 * moved. Recording again (`RECORD_STATIC_PARITY=1`) is a deliberate change to
 * what the static site shows, never a way to make this test pass.
 */

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import type { EntryAdviceIndex } from "../types";
import { resolvePublishedAdvice } from "./adviceSelection";
import { chipPath } from "./chipChoice";
import { TOP100_WEIGHTS, top100Path, top100TargetPath } from "./top100";

const RECORDED = new URL("./adviceSelection.staticParity.json", import.meta.url);
const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const HUMANS = MEMBERS.filter((member) => member.member_kind === "human");
const ENTRY = HUMANS[0]!.entry_id;
const BASE = mockEntryAdviceIndex(ENTRY).payload;
const DEFAULT_RIVAL = BASE.default_rival_entry_id ?? BASE.rival_entry_ids[0]!;
const OTHER_RIVAL = BASE.rival_entry_ids.find((id) => id !== DEFAULT_RIVAL)!;
const DECLARED = BASE.unavailable[0]!;
const WEIGHTS = TOP100_WEIGHTS.filter((weight) => weight !== 0);

const EVIDENCE: EntryAdviceIndex["evidence"] = {
  available: true,
  path: `advice/${ENTRY}/saf-puan/1/hoca-sozu.json`,
  applied_count: 1,
  source_kind: "synthetic_fixture",
  source_label: "club_news_v1.fixture.json",
  clubs_covered: [],
  rule_version: "managers_word_rule_v1",
};

const TOP100: EntryAdviceIndex["top100"] = {
  available: true,
  published_weight: 0,
  weights: [...TOP100_WEIGHTS],
  paths: Object.fromEntries(WEIGHTS.map((w) => [String(w), top100Path(ENTRY, w, false)])),
  // The word was solved with two of the settings only.
  word_paths: Object.fromEntries([5, 20].map((w) => [String(w), top100Path(ENTRY, w, true)])),
  unavailable: [],
  documents: [
    ...[10, 30].map((weight) => ({
      strategy: "saf-puan",
      window: 3,
      rival_entry_id: null,
      weight,
      path: top100TargetPath(
        ENTRY,
        { strategy: "saf-puan", window: 3, rivalEntryId: null },
        weight,
        false,
      )!,
    })),
    {
      strategy: "ortak-koru",
      window: 1,
      rival_entry_id: DEFAULT_RIVAL,
      weight: 20,
      path: top100TargetPath(
        ENTRY,
        { strategy: "ortak-koru", window: 1, rivalEntryId: DEFAULT_RIVAL },
        20,
        false,
      )!,
    },
  ],
} as EntryAdviceIndex["top100"];

const CHIPS: EntryAdviceIndex["chips"] = {
  available: true,
  paths: { wildcard: chipPath(ENTRY, "wildcard"), bboost: chipPath(ENTRY, "bboost") },
  unavailable: [{ chip: "freehit", reason: "already_played" }],
  held: ["wildcard", "bboost", "3xc"],
};

const INDEXES: Record<string, EntryAdviceIndex | null> = {
  "example publish": BASE,
  "manager's word solved": { ...BASE, evidence: EVIDENCE },
  "whole menu": {
    ...BASE,
    evidence: EVIDENCE,
    top100: TOP100,
    chips: CHIPS,
    windows: { ...BASE.windows, "ortak-koru": [1, 3] },
    computed: [
      ...BASE.computed,
      {
        strategy: "ortak-koru",
        rival_entry_id: DEFAULT_RIVAL,
        path: `advice/${ENTRY}/ortak-koru/3/vs-${DEFAULT_RIVAL}.json`,
      },
    ],
  },
  "no Top 100 this run": {
    ...BASE,
    top100: { available: false, reason: "no_top100_this_run" },
    chips: { available: false, reason: "no_chips_this_run" } as EntryAdviceIndex["chips"],
  },
  "empty publish": { ...BASE, strategies: [], computed: [], windows: {} },
  "legacy single window": { ...BASE, windows: undefined },
  "another member's index": { ...BASE, entry_id: ENTRY + 1 },
  "no index": null,
};

const LINKS = [
  "",
  "window=3",
  "window=5",
  "window=9",
  `window=3&rival=${DEFAULT_RIVAL}`,
  "mode=garantici",
  "mode=made-up",
  "mode=ortak-koru",
  "mode=ortak-koru&window=3",
  `mode=ortak-koru&window=3&rival=${OTHER_RIVAL}`,
  `mode=ortak-koru&rival=${OTHER_RIVAL}`,
  `mode=ortak-koru&top100=20`,
  `mode=ortak-koru&rival=${OTHER_RIVAL}&top100=20`,
  "mode=fark-yarat",
  "mode=fark-yarat&rival=99999999",
  `mode=fark-yarat&rival=${ENTRY}`,
  `mode=${DECLARED.strategy}&rival=${DECLARED.rival_entry_id}`,
  "llm=on",
  "llm=on&window=3",
  "llm=on&mode=ortak-koru",
  "top100=20",
  "top100=30&llm=on",
  "top100=20&llm=on",
  "top100=7",
  "top100=10&window=3",
  "top100=20&window=3",
  "top100=20&window=5",
  "chip=wildcard",
  "chip=3xc",
  "chip=freehit",
  "chip=made-up",
  "chip=wildcard&llm=on",
  "chip=wildcard&top100=20",
  "chip=wildcard&window=3",
];

function staticSelections(): Record<string, unknown> {
  const selections: Record<string, unknown> = {};
  for (const [name, index] of Object.entries(INDEXES)) {
    for (const link of LINKS) {
      for (const withContext of [false, true]) {
        const selection = resolvePublishedAdvice(
          new URLSearchParams(link),
          BASE.league_id,
          ENTRY,
          MEMBERS,
          index,
          withContext ? { season: BASE.season, gameweek: BASE.gameweek } : undefined,
        );
        selections[
          `${name} | ${link || "(no parameters)"} | ${withContext ? "page" : "controls"}`
        ] = selection;
      }
    }
  }
  return selections;
}

/** A digest of what JSON keeps of a value: its set keys, in order, and their values. */
function digest(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

describe("the resolver with no compute service", () => {
  it("answers every recorded selection exactly as it did before", () => {
    const selections = staticSelections();
    if (process.env.RECORD_STATIC_PARITY === "1") {
      const digests = Object.fromEntries(
        Object.entries(selections).map(([name, selection]) => [name, digest(selection)]),
      );
      writeFileSync(RECORDED, `${JSON.stringify(digests, null, 2)}\n`);
    }
    const recorded = JSON.parse(readFileSync(RECORDED, "utf8")) as Record<string, string>;
    expect(Object.keys(selections)).toEqual(Object.keys(recorded));
    expect(Object.keys(recorded).length).toBe(Object.keys(INDEXES).length * LINKS.length * 2);
    for (const [name, selection] of Object.entries(selections)) {
      expect(digest(selection), `${name}: ${JSON.stringify(selection)}`).toBe(recorded[name]);
    }
  });

  it("carries no computable facet and no switch on the request", () => {
    for (const [name, selection] of Object.entries(staticSelections())) {
      const keys = Object.keys(selection as object);
      expect(keys, name).not.toContain("computable");
      const request = (selection as { request: object }).request;
      expect(Object.keys(request), name).not.toContain("top100Weight");
      expect(Object.keys(request), name).not.toContain("managersWord");
    }
  });

  it("reads an explicit null the same as no capabilities at all", () => {
    for (const link of LINKS) {
      const args = [new URLSearchParams(link), BASE.league_id, ENTRY, MEMBERS, BASE] as const;
      expect(resolvePublishedAdvice(...args, undefined, null)).toStrictEqual(
        resolvePublishedAdvice(...args),
      );
    }
  });
});
