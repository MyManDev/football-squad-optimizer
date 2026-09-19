/**
 * The resolver with the compute service's capabilities in hand: the published answer stays
 * what it was, and a selection the tree does not list but the service computes is offered
 * to the compute panel instead of being a dead end.
 */

import { describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import type { EntryAdviceIndex } from "../types";
import type { AdviceCapabilities } from "./adviceCapabilities";
import { resolvePublishedAdvice } from "./adviceSelection";
import { chipPath } from "./chipChoice";
import { TOP100_WEIGHTS, top100Path } from "./top100";

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const HUMANS = MEMBERS.filter((member) => member.member_kind === "human");
const ENTRY = HUMANS[0]!.entry_id;
const BASE = mockEntryAdviceIndex(ENTRY).payload;
const DEFAULT_RIVAL = BASE.default_rival_entry_id!;
const OTHER_RIVAL = BASE.rival_entry_ids.find(
  (id) => id !== DEFAULT_RIVAL && !BASE.unavailable.some((row) => row.rival_entry_id === id),
)!;
const DECLARED = BASE.unavailable[0]!;
const WEIGHTS = TOP100_WEIGHTS.filter((weight) => weight !== 0);

const INDEX: EntryAdviceIndex = {
  ...BASE,
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
    paths: Object.fromEntries(WEIGHTS.map((w) => [String(w), top100Path(ENTRY, w, false)])),
    word_paths: { "5": top100Path(ENTRY, 5, true) },
    unavailable: [],
  },
  chips: {
    available: true,
    paths: { wildcard: chipPath(ENTRY, "wildcard") },
    unavailable: [],
    held: ["wildcard"],
  },
};

const WHOLE_MENU: AdviceCapabilities = {
  leagueId: BASE.league_id,
  captureSnapshotId: "example-post-deadline-gw02",
  season: BASE.season,
  gameweek: BASE.gameweek,
  strategies: {
    "saf-puan": { windows: [1, 3, 5], requiresRival: false },
    "ortak-koru": { windows: [1, 3, 5], requiresRival: true },
    "fark-yarat": { windows: [1, 3, 5], requiresRival: true },
  },
  top100Weights: [...TOP100_WEIGHTS],
  managersWord: true,
};
const NO_SWITCHES: AdviceCapabilities = { ...WHOLE_MENU, top100Weights: [0], managersWord: false };

it("offers a held unpublished chip without mistaking the plain file for its answer", () => {
  const caps: AdviceCapabilities = { ...WHOLE_MENU, chipsByEntry: { [ENTRY]: ["bboost"] } };
  const selection = resolve("chip=bboost", caps);
  expect(selection).toMatchObject({
    status: "not-listed",
    path: null,
    request: { chip: "bboost", managersWord: false, top100Weight: 0 },
    chip: { chip: "bboost", notOffered: false },
    computable: { selection: true, chips: ["bboost"] },
  });
  expect(resolve("chip=wildcard", caps).computable?.selection).toBe(false);
  for (const link of ["chip=bboost&top100=20", "chip=bboost&llm=on", "chip=bboost&window=3"]) {
    expect(resolve(link, caps).request.chip).toBeNull();
  }
  expect(resolve("chip=bboost", { ...caps, chipsByEntry: { [ENTRY]: [] } }).chip.chip).toBeNull();
});

function resolve(
  link: string,
  capabilities: AdviceCapabilities | null,
  index: EntryAdviceIndex | null = INDEX,
) {
  return resolvePublishedAdvice(
    new URLSearchParams(link),
    BASE.league_id,
    ENTRY,
    MEMBERS,
    index,
    { season: BASE.season, gameweek: BASE.gameweek },
    capabilities,
  );
}

interface Expected {
  status: string;
  path: string | null;
  computable: boolean;
  rival?: number | null;
  weight?: number;
  word?: boolean;
  chip?: string | null;
}

const TABLE: [string, string, AdviceCapabilities, Expected][] = [
  [
    "the published plain plan is shown and can be recomputed",
    "",
    WHOLE_MENU,
    { status: "ready", path: `advice/${ENTRY}/saf-puan/1.json`, computable: true },
  ],
  [
    "a rival strategy at three weeks against a non-default rival is computable, not listed",
    `mode=ortak-koru&window=3&rival=${OTHER_RIVAL}`,
    WHOLE_MENU,
    { status: "not-listed", path: null, computable: true, rival: OTHER_RIVAL },
  ],
  [
    "a published pair stays published, and the service can redo it",
    `mode=ortak-koru&rival=${OTHER_RIVAL}`,
    WHOLE_MENU,
    {
      status: "ready",
      path: `advice/${ENTRY}/ortak-koru/1/vs-${OTHER_RIVAL}.json`,
      computable: true,
      rival: OTHER_RIVAL,
    },
  ],
  [
    "a Top 100 setting against a non-default rival is computable, and the setting is kept",
    `mode=ortak-koru&rival=${OTHER_RIVAL}&top100=20`,
    WHOLE_MENU,
    { status: "not-listed", path: null, computable: true, rival: OTHER_RIVAL, weight: 20 },
  ],
  [
    "a published setting is read from its file",
    "top100=20",
    WHOLE_MENU,
    { status: "ready", path: top100Path(ENTRY, 20, false), computable: true, weight: 20 },
  ],
  [
    "the word with a setting the publish solved together is read from its file",
    "top100=5&llm=on",
    WHOLE_MENU,
    { status: "ready", path: top100Path(ENTRY, 5, true), computable: true, weight: 5, word: true },
  ],
  [
    "the word with a setting nobody solved together goes to the service, both kept",
    "top100=30&llm=on",
    WHOLE_MENU,
    { status: "not-listed", path: null, computable: true, weight: 30, word: true },
  ],
  [
    "a setting on a five-week plan goes to the service",
    "window=5&top100=10",
    WHOLE_MENU,
    { status: "not-listed", path: null, computable: true, weight: 10 },
  ],
  [
    "the word stays a one-week pure-points switch",
    "window=3&llm=on",
    WHOLE_MENU,
    { status: "ready", path: `advice/${ENTRY}/saf-puan/3.json`, computable: true, word: false },
  ],
  [
    "a service without the switches' inputs leaves an unpublished setting at 0",
    "window=5&top100=10",
    NO_SWITCHES,
    { status: "ready", path: `advice/${ENTRY}/saf-puan/5.json`, computable: true, weight: 0 },
  ],
  [
    "a published switch the service cannot compute is shown and not recomputed",
    "llm=on",
    NO_SWITCHES,
    {
      status: "ready",
      path: `advice/${ENTRY}/saf-puan/1/hoca-sozu.json`,
      computable: false,
      word: true,
    },
  ],
  [
    "a chosen chip is shown from the tree and never sent to the service",
    "chip=wildcard",
    WHOLE_MENU,
    { status: "ready", path: chipPath(ENTRY, "wildcard"), computable: false, chip: "wildcard" },
  ],
  [
    "a switch that is on leaves the chip out, as it always has",
    "chip=wildcard&top100=20",
    WHOLE_MENU,
    {
      status: "ready",
      path: top100Path(ENTRY, 20, false),
      computable: true,
      weight: 20,
      chip: null,
    },
  ],
  [
    "a pair the producer declared impossible stays impossible",
    `mode=${DECLARED.strategy}&rival=${DECLARED.rival_entry_id}`,
    WHOLE_MENU,
    { status: "declared-unavailable", path: null, computable: false },
  ],
  [
    "a rival strategy with nobody named cannot be asked",
    "mode=fark-yarat&rival=99999999",
    WHOLE_MENU,
    { status: "not-listed", path: null, computable: false, rival: null },
  ],
  [
    "a legacy play mode is not something the service computes",
    "mode=garantici",
    WHOLE_MENU,
    { status: "not-listed", path: null, computable: false },
  ],
  [
    "a window that is not one of the three is not computable",
    "window=9",
    WHOLE_MENU,
    { status: "not-listed", path: null, computable: false },
  ],
  [
    "a strategy the service does not list is published-only",
    `mode=ortak-koru&window=3&rival=${OTHER_RIVAL}`,
    { ...WHOLE_MENU, strategies: { "saf-puan": WHOLE_MENU.strategies["saf-puan"]! } },
    { status: "not-listed", path: null, computable: false },
  ],
];

describe("the resolver with the service's capabilities", () => {
  it.each(TABLE)("%s", (_name, link, capabilities, expected) => {
    const selection = resolve(link, capabilities);
    expect(selection.status).toBe(expected.status);
    expect(selection.path).toBe(expected.path);
    expect(selection.computable?.selection).toBe(expected.computable);
    if (expected.rival !== undefined) expect(selection.request.rivalEntryId).toBe(expected.rival);
    if (expected.weight !== undefined) {
      expect(selection.top100.weight).toBe(expected.weight);
      expect(selection.request.top100Weight).toBe(expected.weight);
    }
    if (expected.word !== undefined) {
      expect(selection.evidence.on).toBe(expected.word);
      expect(selection.request.managersWord).toBe(expected.word);
    }
    if (expected.chip !== undefined) expect(selection.chip.chip).toBe(expected.chip);
  });

  it("lists what the controls may enable, beside what was published", () => {
    const selection = resolve("mode=ortak-koru", WHOLE_MENU);
    expect(selection.windows).toEqual([1]); // published
    expect(selection.computable).toMatchObject({
      strategies: ["saf-puan", "ortak-koru", "fark-yarat"],
      windows: [1, 3, 5],
      top100Weights: [...TOP100_WEIGHTS],
      word: false,
    });
    expect(selection.computable?.rivals).toEqual(
      expect.arrayContaining(HUMANS.slice(1).map((member) => member.entry_id)),
    );
    expect(selection.computable?.rivals).not.toContain(ENTRY);
    expect(resolve("", WHOLE_MENU).computable).toMatchObject({ word: true, rivals: [] });
    expect(resolve("", NO_SWITCHES).computable).toMatchObject({
      word: false,
      top100Weights: [0],
    });
  });

  it("drops a pure-points window the producer declared impossible", () => {
    const index: EntryAdviceIndex = {
      ...INDEX,
      unavailable: [
        ...INDEX.unavailable,
        { strategy: "saf-puan", rival_entry_id: null, window: 5, reason: "no plan" },
      ],
    };
    expect(resolve("", WHOLE_MENU, index).computable?.windows).toEqual([1, 3]);
    expect(resolve("window=5", WHOLE_MENU, index)).toMatchObject({
      status: "declared-unavailable",
      computable: { selection: false },
    });
  });

  it("computes nothing without a readable index, and says the mode is dynamic", () => {
    expect(resolve("", WHOLE_MENU, null)).toMatchObject({
      status: "index-missing",
      computable: { selection: false, strategies: [] },
    });
    expect(resolve("", WHOLE_MENU, { ...INDEX, entry_id: ENTRY + 1 })).toMatchObject({
      status: "index-error",
      computable: { selection: false },
    });
  });

  it.each([
    ["another league", { ...WHOLE_MENU, leagueId: BASE.league_id + 1 }],
    ["another gameweek", { ...WHOLE_MENU, gameweek: BASE.gameweek + 1 }],
    ["another season", { ...WHOLE_MENU, season: "1999-00" }],
  ])("ignores capabilities that speak about %s", (_name, capabilities) => {
    const link = `mode=ortak-koru&window=3&rival=${OTHER_RIVAL}&top100=20`;
    expect(resolve(link, capabilities)).toStrictEqual(resolve(link, null));
    expect(resolve(link, capabilities).computable).toBeUndefined();
  });
});
