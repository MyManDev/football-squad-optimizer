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
import type { AdviceCapabilities } from "./adviceCapabilities";
import { resolvePublishedAdvice } from "./adviceSelection";
import { COMPUTE_COPY } from "./computeCopy";
import { MemberDecisionControls } from "./MemberDecisionControls";
import { TOP100_COPY } from "./top100Copy";

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
const DEVICE_INDEX: EntryAdviceIndex = {
  ...mockEntryAdviceIndex(ENTRY).payload,
  gameweek: 7,
  menu: "device",
  source_snapshot_id: "device-menu-capture",
  windows: { "saf-puan": [], "ortak-koru": [], "fark-yarat": [] },
  computed: [],
  unavailable: [],
  chip_states: SQUAD.chips,
  chips: { available: false, reason: "on_device" },
  top100: { available: false, reason: "on_device" },
  evidence: { available: false, reason: "on_device" },
};
const RIVAL = 35249002;
const READS = {
  ...NO_DEVICE_RIVALS,
  squads: [
    { ...mockEntrySquadEnvelopes[RIVAL]!.payload, source_snapshot_id: SQUAD.source_snapshot_id },
  ],
};

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

  it.each([
    null,
    DEVICE_INDEX,
    { ...mockEntryAdviceIndex(ENTRY).payload, gameweek: 7, chips: undefined },
  ])(
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

  it("keeps device weights and the default plan available through the device index", () => {
    for (const query of ["", "top100=20"]) {
      const selected = resolve(query, DEVICE_INDEX);
      expect(selected.path).toBeNull();
      expect(deviceSelection(deviceRequestFor(selected), SQUAD)).toEqual(
        query ? { kind: "top100", weight: 20 } : { kind: "plain" },
      );
    }
  });

  it("retains the rival and its weight when neither has a published answer", () => {
    const selected = memberSelection({
      squad: SQUAD,
      members: MEMBERS,
      index: null,
      capabilities: null,
      deviceRivals: READS,
    }).resolve(new URLSearchParams(`mode=ortak-koru&rival=${RIVAL}&top100=20`));
    expect(selected.path).toBeNull();
    expect(deviceSelection(deviceRequestFor(selected), SQUAD)).toEqual({
      kind: "rival",
      strategy: "ortak-koru",
      rivalEntryId: RIVAL,
      weight: 20,
    });
  });

  it.each(["tr", "en"] as const)("offers the device's weight beside a rival in %s", (language) => {
    render(
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter
          initialEntries={[`/league/352490/members/${ENTRY}?mode=ortak-koru&rival=${RIVAL}`]}
        >
          <MemberDecisionControls
            entryId={ENTRY}
            members={MEMBERS}
            index={null}
            onDevice={deviceComputable(SQUAD, MEMBERS, READS)}
            part="top100"
          />
        </MemoryRouter>
      </LanguageProvider>,
    );
    const weight = document.querySelector<HTMLInputElement>('input[name="top100"][value="20"]')!;
    expect(weight).toBeEnabled();
    fireEvent.click(weight);
    expect(weight).toBeChecked();
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

describe("a rejected advice index beside the device's choices", () => {
  const PUBLISHED = { ...mockEntryAdviceIndex(ENTRY).payload, gameweek: 7 };
  const CAPABILITIES: AdviceCapabilities = {
    leagueId: SQUAD.league_id,
    captureSnapshotId: "device-menu-capture",
    season: SQUAD.season,
    gameweek: SQUAD.gameweek,
    strategies: { "saf-puan": { windows: [1], requiresRival: false } },
    top100Weights: [0],
    managersWord: false,
  };

  it.each([
    ["gameweek", { ...PUBLISHED, gameweek: 8 }],
    ["league", { ...PUBLISHED, league_id: SQUAD.league_id + 1 }],
    ["season", { ...PUBLISHED, season: "1999-00" }],
  ] as const)("stays unreadable for an index from another %s", (_name, index) => {
    for (const capabilities of [null, CAPABILITIES]) {
      for (const [query, device] of [
        ["chip=3xc", { kind: "chip", chip: "3xc" }],
        ["top100=20", { kind: "top100", weight: 20 }],
      ] as const) {
        const params = new URLSearchParams(`mode=saf-puan&${query}`);
        const selected = memberSelection({
          squad: SQUAD,
          members: MEMBERS,
          index,
          capabilities,
          deviceRivals: NO_DEVICE_RIVALS,
        }).resolve(params);
        expect(selected.status).toBe("index-error");
        expect(selected.path).toBeNull();
        // The controls are given no index while it is rejected; the device is asked for
        // the same choice they show.
        const controls = resolvePublishedAdvice(
          params,
          0,
          ENTRY,
          MEMBERS,
          null,
          undefined,
          capabilities,
          DEVICE,
        );
        expect(deviceSelection(deviceRequestFor(selected), SQUAD)).toEqual(device);
        expect(deviceSelection(deviceRequestFor(controls), SQUAD)).toEqual(device);
      }
    }
  });
});

describe("the Top 100 note beside a device weight", () => {
  it.each([
    ["tr", "no index", null],
    ["en", "no index", null],
    ["tr", "the device index", DEVICE_INDEX],
    ["en", "the device index", DEVICE_INDEX],
  ] as const)(
    "names the checked device weight as computable in %s with %s",
    (language, _name, index) => {
      render(
        <LanguageProvider initialLanguage={language}>
          <MemoryRouter
            initialEntries={[`/league/352490/members/${ENTRY}?mode=saf-puan&top100=20`]}
          >
            <MemberDecisionControls
              entryId={ENTRY}
              members={MEMBERS}
              index={index}
              onDevice={DEVICE}
              part="top100"
            />
          </MemoryRouter>
        </LanguageProvider>,
      );
      expect(
        document.querySelector<HTMLInputElement>('input[name="top100"][value="20"]'),
      ).toBeChecked();
      const fieldset = document.querySelector("fieldset")!;
      expect(fieldset).toHaveTextContent(COMPUTE_COPY[language].top100Computable);
      for (const sentence of Object.values(TOP100_COPY[language].unavailableReasons)) {
        expect(fieldset).not.toHaveTextContent(sentence);
      }
    },
  );
});

describe("the Top 100 note where the link leaves the device's weight out", () => {
  // The service with the word and no Top 100 setting of its own.
  const SERVICE: AdviceCapabilities = {
    leagueId: DEVICE_INDEX.league_id,
    captureSnapshotId: "device-menu-capture",
    season: SQUAD.season,
    gameweek: SQUAD.gameweek,
    strategies: { "saf-puan": { windows: [1], requiresRival: false } },
    top100Weights: [0],
    managersWord: true,
  };
  const PREFERENCES = `preferences=${encodeURIComponent(JSON.stringify({ no_hits: true }))}`;

  it.each([
    ["llm=on", "no index", null, null],
    ["llm=on", "the device index", DEVICE_INDEX, null],
    ["llm=on", "the service with the word", DEVICE_INDEX, SERVICE],
    ["model=football", "no index", null, null],
    ["model=football", "the service", DEVICE_INDEX, SERVICE],
    [PREFERENCES, "no index", null, null],
    [PREFERENCES, "the service", DEVICE_INDEX, SERVICE],
  ] as const)("still says only 0 is available with %s and %s", (query, _name, index, service) => {
    for (const language of ["tr", "en"] as const) {
      render(
        <LanguageProvider initialLanguage={language}>
          <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}?mode=saf-puan&${query}`]}>
            <MemberDecisionControls
              entryId={ENTRY}
              members={MEMBERS}
              index={index}
              capabilities={service}
              onDevice={DEVICE}
              part="top100"
            />
          </MemoryRouter>
        </LanguageProvider>,
      );
      // Even a link that names the weight does not ask the device for it here.
      const params = new URLSearchParams(`mode=saf-puan&${query}&top100=20`);
      const selected = resolvePublishedAdvice(
        params,
        index?.league_id ?? 0,
        ENTRY,
        MEMBERS,
        index,
        undefined,
        service,
        DEVICE,
      );
      expect(deviceSelection(deviceRequestFor(selected), SQUAD)).not.toEqual({
        kind: "top100",
        weight: 20,
      });
      const fieldset = document.querySelector("fieldset")!;
      expect(fieldset).not.toHaveTextContent(COMPUTE_COPY[language].top100Computable);
      expect(fieldset).toHaveTextContent(TOP100_COPY[language].unavailableReasons.unknown);
      cleanup();
    }
  });
});
