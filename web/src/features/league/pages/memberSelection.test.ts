/**
 * What the device is asked for is the selection the page shows, switches included: a
 * static build's request carries none of them, and a switch left out would have the
 * device solve the plain plan in its place.
 */

import { describe, expect, it } from "vitest";

import {
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
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

function askedOfDevice(link: string) {
  const { resolve } = memberSelection({
    squad,
    members: mockLeagueMembersEnvelope.payload.members,
    index: INDEX,
    capabilities: null,
    deviceRivals: NO_DEVICE_RIVALS,
  });
  return deviceRequestFor(resolve(new URLSearchParams(link)));
}

describe("what the device is asked for", () => {
  it("carries the manager's word the page shows, so the device leaves that plan to the service", () => {
    const on = askedOfDevice("mode=saf-puan&window=1&llm=on");
    expect(on.managersWord).toBe(true);
    expect(deviceSelection(on, squad)).toBeNull();

    const off = askedOfDevice("mode=saf-puan&window=1");
    expect(off.managersWord).toBe(false);
    expect(deviceSelection(off, squad)).toEqual({ kind: "plain" });
  });
});
