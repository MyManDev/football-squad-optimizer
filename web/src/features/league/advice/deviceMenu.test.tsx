import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { deviceComputable, NO_DEVICE_RIVALS } from "../device/computable";
import { deviceSelection } from "../device/selection";
import { deviceRequestFor, memberSelection } from "../pages/memberSelection";
import type { EntryAdviceIndex, EntrySquad } from "../types";
import { MemberDecisionControls } from "./MemberDecisionControls";

afterEach(cleanup);

const ENTRY = 35249001;
const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const AVAILABLE = { state: "available", start_event: 1, stop_event: 19, gameweek: null } as const;
const SQUAD: EntrySquad = {
  ...mockEntrySquadEnvelopes[ENTRY]!.payload,
  source_snapshot_id: "device-menu-capture",
  gameweek: 7,
  device_plan: {
    held: [],
    bank_tenths: 0,
    free_transfers: 1,
    sell_tenths: {},
    top100_weights: [20],
  },
  chips: {
    known: true,
    gameweek: 7,
    states: {
      wildcard: { first_half: { ...AVAILABLE, state: "used", gameweek: 5 }, second_half: null },
      freehit: { first_half: null, second_half: { ...AVAILABLE, start_event: 20, stop_event: 38 } },
      bboost: { first_half: { ...AVAILABLE, stop_event: 6 }, second_half: null },
      "3xc": { first_half: AVAILABLE, second_half: null },
    },
  },
};
const DEVICE = deviceComputable(SQUAD, MEMBERS, NO_DEVICE_RIVALS)!;

function resolve(query: string, index: EntryAdviceIndex | null = null) {
  return memberSelection({
    squad: SQUAD,
    members: MEMBERS,
    index,
    capabilities: null,
    deviceRivals: NO_DEVICE_RIVALS,
  }).resolve(new URLSearchParams(`mode=saf-puan&${query}`));
}

describe("the device menu without published chip answers", () => {
  it("offers only a held chip whose window includes this week", () => {
    expect(DEVICE.chips).toEqual(["3xc"]);
    expect(
      deviceComputable({ ...SQUAD, chips: undefined }, MEMBERS, NO_DEVICE_RIVALS)?.chips,
    ).toEqual([]);
    expect(
      deviceComputable(
        { ...SQUAD, chips: { ...SQUAD.chips!, known: false } },
        MEMBERS,
        NO_DEVICE_RIVALS,
      )?.chips,
    ).toEqual([]);
  });

  it.each([null, { ...mockEntryAdviceIndex(ENTRY).payload, gameweek: 7, chips: undefined }])(
    "asks the worker for the chosen chip without reading a nonexistent answer file (%j)",
    (index) => {
      const selected = resolve("chip=3xc", index);
      expect(selected.status).toBe("not-listed");
      expect(selected.path).toBeNull();
      expect(selected.chip.chip).toBe("3xc");
      expect(selected.chip.options).toEqual([]);
      expect(deviceSelection(deviceRequestFor(selected), SQUAD)).toEqual({
        kind: "chip",
        chip: "3xc",
      });
    },
  );

  it.each(["window=3", "mode=ortak-koru", "llm=on", "model=football", "top100=20"])(
    "keeps the chip off for an incompatible selection: %s",
    (query) => {
      const selected = memberSelection({
        squad: SQUAD,
        members: MEMBERS,
        index: null,
        capabilities: null,
        deviceRivals: NO_DEVICE_RIVALS,
      }).resolve(new URLSearchParams(`${query}&chip=3xc`));
      expect(selected.chip.chip).toBeNull();
    },
  );

  it("retains a supported Top 100 weight without a published index", () => {
    const selected = resolve("top100=20");
    expect(selected.path).toBeNull();
    expect(deviceSelection(deviceRequestFor(selected), SQUAD)).toEqual({
      kind: "top100",
      weight: 20,
    });
  });

  it("does not offer unknown, played or future chips", () => {
    for (const chip of ["wildcard", "freehit", "bboost", "auto", "unknown"]) {
      expect(resolve(`chip=${chip}`).chip.chip).toBeNull();
    }
  });

  it.each(["tr", "en"] as const)("lets the visitor choose the held chip in %s", (language) => {
    function Location() {
      return <output data-testid="location">{useLocation().search}</output>;
    }
    render(
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}?mode=saf-puan`]}>
          <MemberDecisionControls
            entryId={ENTRY}
            members={MEMBERS}
            index={null}
            onDevice={DEVICE}
          />
          <Location />
        </MemoryRouter>
      </LanguageProvider>,
    );
    const chips = Array.from(document.querySelectorAll<HTMLInputElement>('input[name="chip"]'));
    const triple = chips.find((input) => input.value === "3xc")!;
    expect(triple).toBeEnabled();
    expect(chips.find((input) => input.value === "wildcard")).toBeDisabled();
    fireEvent.click(triple);
    expect(new URLSearchParams(screen.getByTestId("location").textContent!).get("chip")).toBe(
      "3xc",
    );
    expect(triple).toBeChecked();
  });
});
