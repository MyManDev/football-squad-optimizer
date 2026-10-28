/**
 * The week screen's arrival (#1136): the decision card rises into place, its boards follow it
 * a step apart, the gain's bar fills to its value while the figure, already final, comes up
 * beside it, and the pitch's plates appear one after another from the keeper. Each part moves
 * once for the page, in the motion tokens' times, and not at all under reduced motion. Between
 * member pages the pinned top bar holds still under the crossfade, and no page names it twice.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { MOTION_MS, REDUCED_MOTION_QUERY } from "../../../design/motion";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { LanguageToggle } from "../../../i18n/LanguageToggle";
import { withLeague } from "../../../testSupport/league";
import type { AdviceMove, EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";
import type { LeagueMemberViewProps } from "./memberPageTypes";
import { APPEAR, FILL, RISE } from "./weekArrival";

const ENTRY = 35249001;
const EXAMPLE = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
const move = (id: number, delta: number): AdviceMove => ({
  move_id: `m${id}`,
  player_out: { player_id: id, name: `P${id}`, short_name: "", position: "MID", team: "X" },
  player_in: { player_id: id + 1, name: `P${id + 1}`, short_name: "", position: "MID", team: "X" },
  expected_points_delta: delta,
  reason_code: "points_gain",
});
// Two moves published as shares, so the gain is drawn as a bar.
const BASE: LeagueViewEnvelope<EntryAdvice> = {
  ...EXAMPLE,
  payload: { ...EXAMPLE.payload, moves: [move(1, 2.4), move(3, 0.6)], expected_gain_vs_hold: 3 },
};

let started: { element: Element; keyframes: Keyframe[]; options: KeyframeAnimationOptions }[];
/** The arrival's own starts, apart from the boards' motion on the same page. */
const arrival = () => started.filter(({ keyframes }) => [RISE, FILL, APPEAR].includes(keyframes));
const of = (element: Element) => arrival().filter((start) => start.element === element);
const timed = (duration: number) => expect.objectContaining({ duration });

beforeEach(() => {
  started = [];
  // jsdom has no Web Animations; this records each start.
  Object.defineProperty(Element.prototype, "animate", {
    configurable: true,
    writable: true,
    value(this: Element, keyframes: Keyframe[], options: KeyframeAnimationOptions) {
      started.push({ element: this, keyframes, options });
      return { playState: "running", cancel() {} } as unknown as Animation;
    },
  });
});

afterEach(() => {
  cleanup();
  delete (Element.prototype as { animate?: unknown }).animate;
  delete (window as { matchMedia?: unknown }).matchMedia;
});

const view = (props: Partial<LeagueMemberViewProps> = {}) => (
  <LanguageProvider initialLanguage="tr">
    <LanguageToggle />
    <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}`]}>
      {withLeague(
        <LeagueMemberView
          squad={mockEntrySquadEnvelopes[ENTRY]!}
          advice={BASE}
          members={mockLeagueMembersEnvelope.payload.members}
          index={mockEntryAdviceIndex(ENTRY).payload}
          {...props}
        />,
      )}
    </MemoryRouter>
  </LanguageProvider>
);
const card = () => document.querySelector('[data-mark="decision"]')!;
const part = (name: string) => card().querySelector(`[data-arrival="${name}"]`)!;
const rows = () => [...card().querySelectorAll('[data-arrival="row"]')];
const plates = () => [...document.querySelectorAll('[data-mark="pitch"] [data-plate]')];

describe("the week screen's arrival", () => {
  it("raises the card, each board a step after it, and fills the bar beside the figure", () => {
    render(view());
    expect(of(card())).toEqual([
      { element: card(), keyframes: RISE, options: timed(MOTION_MS.ui) },
    ]);
    const step = MOTION_MS.uiFast / 3;
    expect(rows().map((row) => of(row)[0]!.options.delay)).toEqual([step, 2 * step]);
    expect(of(part("bar"))).toEqual([
      { element: part("bar"), keyframes: FILL, options: timed(MOTION_MS.data) },
    ]);
    // Its final value from the first frame: it comes up with the bar and never counts.
    expect(part("gain")).toHaveTextContent("+3,0");
    expect(of(part("gain"))).toEqual([expect.objectContaining({ options: timed(MOTION_MS.data) })]);
  });

  it("brings the plates up in the pitch's order, keeper first, in the data time", () => {
    // Opacity only: no plate's box, nor a mark inside it, is ever drawn smaller than at rest.
    expect(APPEAR.flatMap((frame) => Object.keys(frame))).toEqual(["opacity", "opacity"]);
    render(view());
    expect(plates()).toHaveLength(11);
    plates().forEach((plate, index) =>
      expect(of(plate)).toEqual([
        {
          element: plate,
          keyframes: APPEAR,
          options: expect.objectContaining({
            duration: MOTION_MS.data,
            delay: (index * MOTION_MS.uiFast) / 6,
          }),
        },
      ]),
    );
  });

  it("moves once for the page: not on a re-render, a new language or a new plan", () => {
    const { rerender } = render(view());
    const count = arrival().length;
    rerender(view());
    fireEvent.click(screen.getByRole("button", { name: "EN · English" }));
    rerender(view({ advice: { ...BASE, payload: { ...BASE.payload, moves: [move(5, 1)] } } }));
    expect(arrival()).toHaveLength(count);
  });

  it("raises the card and the plates on arrival, and the boards once the plan is read", () => {
    const { rerender } = render(view({ adviceLoading: true }));
    expect(of(card())).toHaveLength(1);
    expect(plates().map((plate) => of(plate).length)).toEqual(Array(11).fill(1));
    expect(arrival().filter(({ keyframes }) => keyframes === FILL)).toEqual([]);
    rerender(view());
    expect(rows().map((row) => of(row).length)).toEqual([1, 1]);
    expect(of(part("bar"))).toHaveLength(1);
    expect(of(card())).toHaveLength(1);
  });

  it("moves nothing under reduced motion, every part drawn at rest", () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: (query: string) => ({
        matches: query === REDUCED_MOTION_QUERY,
        addEventListener() {},
        removeEventListener() {},
      }),
    });
    render(view());
    expect(started).toEqual([]);
    expect(rows()).toHaveLength(2);
    expect(part("gain")).toHaveTextContent("+3,0");
  });
});

describe("the top bar between member pages", () => {
  const SRC = join(__dirname, "../../..");
  const css = (path: string) => readFileSync(path, "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");

  it("carries the crossfade's name where it is pinned, and gives it up under the drawer", () => {
    render(view());
    const bars = [...document.querySelectorAll(".topBar")];
    expect(bars.map((bar) => bar.tagName)).toEqual(["HEADER"]);
    const page = css(join(__dirname, "LeagueMemberPage.module.css"));
    const pinned = page.match(/@media \(min-width: 600px\) \{([\s\S]*?)\n\}/)?.[1] ?? "";
    expect(pinned).toMatch(
      /\.topBar\s*\{[^}]*position: sticky;[^}]*view-transition-name: member-bar;/,
    );
    expect(pinned).toMatch(/\[data-drawer="open"\]\) \.topBar\s*\{\s*view-transition-name: none;/);
  });

  it("is the one name any stylesheet gives, timed as the crossfade", () => {
    const named = readdirSync(SRC, { recursive: true, encoding: "utf-8" })
      .filter((file) => file.endsWith(".css"))
      .flatMap((file) => css(join(SRC, file)).match(/view-transition-name: (?!none)[\w-]+/g) ?? []);
    expect(named).toEqual(["view-transition-name: member-bar"]);
    expect(css(join(SRC, "design/transitions.css"))).toMatch(
      /::view-transition-group\(member-bar\),\s*::view-transition-old\(member-bar\),\s*::view-transition-new\(member-bar\)\s*\{[^}]*animation-duration: var\(--motion-ui\);/,
    );
  });
});
