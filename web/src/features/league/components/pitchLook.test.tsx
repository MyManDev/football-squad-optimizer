/**
 * The viewer's pitch look (#1136): the grass's pattern and the plates' club colours, chosen
 * under the bench, kept in this browser, shown on the pitch at once, and never moving.
 * Unknown or unreadable values give the default look.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { CLUB_COLOURS, clubCode } from "../../../lib/clubs";
import { withLeague } from "../../../testSupport/league";
import { MemberSquad } from "../pages/MemberSquad";
import { squadOnPitch } from "../pages/squadOnPitch";
import {
  clubPlate,
  DEFAULT_PITCH_LOOK,
  forgetPitchLook,
  PITCH_LOOK_STORAGE_KEY,
  readPitchLook,
} from "./pitchLook";

const ENTRY = 35249001;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;
const PLAN = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1).payload;
const COPY = MESSAGES.tr.leagueMembers;
// The fixture's clubs are invented, so each is given a real club's code in turn, as a
// fixture list would print it.
const CODES = new Map(
  [...new Set(PLAN.starting_xi!.map((player) => player.team))].map((team, index) => [
    team.trim().toLocaleLowerCase("en-GB"),
    Object.keys(CLUB_COLOURS)[index % Object.keys(CLUB_COLOURS).length]!,
  ]),
);

beforeEach(() => {
  window.localStorage.clear();
  forgetPitchLook();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function view() {
  return (
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter>
        {withLeague(
          <MemberSquad
            onPitch={squadOnPitch(PLAN, SQUAD.payload)}
            plan={PLAN}
            codes={CODES}
            list={null}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>
  );
}

const pitch = (container: HTMLElement) => container.querySelector('[data-mark="pitch"]')!;
const plates = (container: HTMLElement) => [
  ...pitch(container).querySelectorAll<HTMLElement>('[role="listitem"] > div > div'),
];
const group = (name: string) => screen.getByRole("group", { name });

describe("the stored look", () => {
  it("is the default with nothing stored, an unknown value or unreadable storage", () => {
    expect(readPitchLook()).toEqual(DEFAULT_PITCH_LOOK);
    window.localStorage.setItem(PITCH_LOOK_STORAGE_KEY, "{not json");
    expect(readPitchLook()).toEqual(DEFAULT_PITCH_LOOK);
    window.localStorage.setItem(
      PITCH_LOOK_STORAGE_KEY,
      JSON.stringify({ grass: "neon", clubColours: "yes" }),
    );
    expect(readPitchLook()).toEqual({ grass: "stripes", clubColours: false });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readPitchLook()).toEqual(DEFAULT_PITCH_LOOK);
  });

  it("reads a stored choice back", () => {
    window.localStorage.setItem(
      PITCH_LOOK_STORAGE_KEY,
      JSON.stringify({ grass: "checks", clubColours: true }),
    );
    expect(readPitchLook()).toEqual({ grass: "checks", clubColours: true });
  });
});

describe("the look under the bench", () => {
  it("starts on stripes with white plates", () => {
    const { container } = render(view());
    expect(pitch(container).getAttribute("data-grass")).toBe("stripes");
    expect(
      within(group(COPY.pitchLookLabel)).getByRole("button", { pressed: true }).textContent,
    ).toBe(COPY.pitchLookStripes);
    expect(
      within(group(COPY.clubColoursLabel)).getByRole("button", { pressed: true }).textContent,
    ).toBe(COPY.clubColoursOff);
    expect(pitch(container).querySelectorAll("[data-club]")).toHaveLength(0);
  });

  it("changes the grass at once, keeps it in this browser and moves nothing", () => {
    const animate = vi.fn();
    Object.defineProperty(Element.prototype, "animate", {
      configurable: true,
      writable: true,
      value: animate,
    });
    const { container } = render(view());
    fireEvent.click(
      within(group(COPY.pitchLookLabel)).getByRole("button", { name: COPY.pitchLookPlain }),
    );
    expect(pitch(container).getAttribute("data-grass")).toBe("plain");
    expect(JSON.parse(window.localStorage.getItem(PITCH_LOOK_STORAGE_KEY)!)).toEqual({
      grass: "plain",
      clubColours: false,
    });
    expect(animate).not.toHaveBeenCalled();
    delete (Element.prototype as { animate?: unknown }).animate;
  });

  it("draws each plate in its club's colours, and the choice outlasts a reload", () => {
    const first = render(view());
    fireEvent.click(
      within(group(COPY.clubColoursLabel)).getByRole("button", { name: COPY.clubColoursOn }),
    );
    const drawn = plates(first.container);
    expect(drawn.length).toBe(11);
    const expected = PLAN.starting_xi!.map((player) => clubPlate(clubCode(player.team, CODES)));
    const coloured = drawn.filter((plate) => plate.hasAttribute("data-club"));
    expect(coloured.length).toBe(expected.filter(Boolean).length);
    expect(coloured.length).toBeGreaterThan(0);
    // A plate in its club's first colour is itself the swatch, so it draws none of its own.
    expect(coloured.some((plate) => plate.dataset.club === "primary")).toBe(true);
    const pairs = expected.filter(Boolean).map((plate) => `${plate!.fill} ${plate!.text}`);
    for (const plate of coloured)
      expect(pairs).toContain(
        `${plate.style.getPropertyValue("--plate-fill")} ${plate.style.getPropertyValue("--plate-text")}`,
      );
    first.unmount();
    forgetPitchLook();
    const again = render(view());
    expect(plates(again.container).some((plate) => plate.hasAttribute("data-club"))).toBe(true);
  });

  it("follows the choice for the visit where storage cannot be written", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("full");
    });
    const { container } = render(view());
    fireEvent.click(
      within(group(COPY.pitchLookLabel)).getByRole("button", { name: COPY.pitchLookChecks }),
    );
    expect(pitch(container).getAttribute("data-grass")).toBe("checks");
  });
});
