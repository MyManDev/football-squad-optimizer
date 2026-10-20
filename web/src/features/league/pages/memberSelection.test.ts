/**
 * What the device is asked for carries the manager's word the page shows: a static
 * build's request leaves the word out, and a word left out would have the device solve
 * the plain plan in its place.
 */

import { describe, expect, it } from "vitest";

import {
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import type { AdviceCapabilities } from "../advice/adviceCapabilities";
import { NO_DEVICE_RIVALS } from "../device/computable";
import { deviceSelection } from "../device/selection";
import type { EntryAdviceIndex } from "../types";
import { deviceRequestFor, memberSelection } from "./memberSelection";

const ENTRY = 35249001;
const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
const INDEX: EntryAdviceIndex = {
  ...mockEntryAdviceIndex(ENTRY).payload,
  evidence: {
    available: true,
    path: `advice/${ENTRY}/saf-puan/1/hoca-sozu.json`,
    applied_count: 1,
    source_kind: "synthetic_fixture",
    source_label: "club_news_v1.fixture.json",
    clubs_covered: ["Arsenal"],
    rule_version: "managers_word_rule_v1",
  },
};
const CAPABILITIES: AdviceCapabilities = {
  leagueId: squad.league_id,
  captureSnapshotId: "example-post-deadline-gw02",
  season: squad.season,
  gameweek: squad.gameweek,
  strategies: { "saf-puan": { windows: [1, 3, 5], requiresRival: false } },
  top100Weights: [0],
  managersWord: true,
};

function selectionFor(
  link: string,
  index: EntryAdviceIndex = INDEX,
  capabilities: AdviceCapabilities | null = null,
) {
  const { resolve } = memberSelection({
    squad,
    members: mockLeagueMembersEnvelope.payload.members,
    index,
    capabilities,
    deviceRivals: NO_DEVICE_RIVALS,
  });
  return resolve(new URLSearchParams(link));
}

describe("what the device is asked for", () => {
  it("carries the manager's word the page shows, so the device leaves that plan to the service", () => {
    const on = deviceRequestFor(selectionFor("mode=saf-puan&window=1&llm=on"));
    expect(on.managersWord).toBe(true);
    expect(deviceSelection(on, squad)).toBeNull();

    const off = deviceRequestFor(selectionFor("mode=saf-puan&window=1"));
    expect(off.managersWord).toBe(false);
    expect(deviceSelection(off, squad)).toEqual({ kind: "plain" });
  });

  it("keeps the word the request already carries where the page shows it off", () => {
    // The producer declared the one-week plan impossible: the page shows no word, and the
    // request the service would be asked still carries it.
    const index: EntryAdviceIndex = {
      ...INDEX,
      unavailable: [
        ...INDEX.unavailable,
        { strategy: "saf-puan", rival_entry_id: null, window: 1, reason: "no plan" },
      ],
    };
    const selection = selectionFor("mode=saf-puan&window=1&llm=on", index, CAPABILITIES);
    expect(selection).toMatchObject({
      status: "declared-unavailable",
      request: { managersWord: true },
      evidence: { on: false },
    });
    const asked = deviceRequestFor(selection);
    expect(asked.managersWord).toBe(true);
    expect(deviceSelection(asked, squad)).toBeNull();
  });
});
