/**
 * The model-switch highlight on the member page (#1131): after a switch of prediction model,
 * the players the new plan brings into the eleven or onto the bench carry a mark, named in
 * their text, and their plates rise once, and a line under the gain strip says how many
 * changed, the number of marks, and counts the points difference up from zero. Unchanged
 * players stay as they are; a switch of anything else marks nothing; under reduced motion
 * nothing moves and the marks and the line are the same.
 */
import { cleanup, render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { forgetCounts } from "../../../design/countMotion";
import { REDUCED_MOTION_QUERY } from "../../../design/motion";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { withLeague } from "../../../testSupport/league";
import { forgetShownPlans } from "../advice/modelSwitch";
import type { AdvicePlayer, EntryAdvice, LeagueViewEnvelope } from "../types";
import { AdviceDecision } from "./MemberAdviceCard";
import { MemberSquad } from "./MemberSquad";
import { squadOnPitch } from "./squadOnPitch";

const ENTRY = 35249001;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;
const EXAMPLE = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
const COPY = MESSAGES.tr.leagueMembers;

let started: { element: Element; keyframes: Keyframe[] }[] = [];

beforeEach(() => {
  forgetShownPlans();
  forgetCounts();
  started = [];
  Object.defineProperty(Element.prototype, "animate", {
    configurable: true,
    writable: true,
    value(this: Element, keyframes: Keyframe[]) {
      started.push({ element: this, keyframes });
      return {
        playState: "running",
        cancel: vi.fn(),
        addEventListener() {},
        effect: { getComputedTiming: () => ({ progress: null }) },
      } as unknown as Animation;
    },
  });
});

afterEach(() => {
  cleanup();
  delete (Element.prototype as { animate?: unknown }).animate;
  delete (window as { matchMedia?: unknown }).matchMedia;
});

const POSITIONS = [
  "GK",
  "DEF",
  "DEF",
  "DEF",
  "DEF",
  "MID",
  "MID",
  "MID",
  "MID",
  "FWD",
  "FWD",
] as const;

function player(id: number, index: number): AdvicePlayer {
  return {
    player_id: id,
    name: `Player ${id}`,
    short_name: `P${id}`,
    position: POSITIONS[index] ?? "MID",
    team: "X",
    expected_points: 5,
  };
}

function plan(
  model: "current" | "football",
  eleven: number[],
  points = 60,
  patch: Partial<EntryAdvice> = {},
  bench: number[] = [91, 92, 93, 94],
): LeagueViewEnvelope<EntryAdvice> {
  return {
    ...EXAMPLE,
    payload: {
      ...EXAMPLE.payload,
      starting_xi: eleven.map(player),
      bench: bench.map((id, i) => ({
        ...player(id, i),
        position: i === 0 ? "GK" : "DEF",
      })),
      captain: player(eleven[10]!, 10),
      vice_captain: player(eleven[9]!, 9),
      solver_status: "OPTIMAL",
      moves: [],
      expected_own_points: points,
      transfer_hit_points: 0,
      prediction_model:
        model === "football"
          ? { id: "football", version: "v1", experimental: true, fingerprint: "f" }
          : undefined,
      ...patch,
    },
  };
}

const CURRENT = Array.from({ length: 11 }, (_, i) => 101 + i);
// The football model keeps nine of them and brings in 201 and 202.
const FOOTBALL = [...CURRENT.slice(0, 8), 201, 202, CURRENT[10]!];

function view(envelope: LeagueViewEnvelope<EntryAdvice>) {
  return (
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter>
        {withLeague(
          <>
            <MemberSquad
              onPitch={squadOnPitch(envelope.payload, SQUAD.payload)}
              plan={envelope.payload}
              codes={new Map()}
              list={null}
            />
            <AdviceDecision shown={{ envelope, origin: "computed" }} squad={SQUAD} />
          </>,
        )}
      </MemoryRouter>
    </LanguageProvider>
  );
}

const marked = (container: HTMLElement) =>
  [...container.querySelectorAll("[data-model-changed]")].map(
    (token) => token.querySelector("[data-plate]")!.textContent,
  );

/** The line's count of changed players, as the copy writes it. */
const said = (container: HTMLElement, count: number) =>
  container
    .querySelector("[data-model-change]")!
    .textContent!.includes(COPY.modelChangePlayers(COPY.modelNames.football, count));

describe("the model-switch highlight", () => {
  it("marks only the players the new model brings in, and says how many and by how much", () => {
    const { container, rerender } = render(view(plan("current", CURRENT, 60)));
    expect(container.querySelectorAll("[data-model-changed]")).toHaveLength(0);
    expect(container.querySelector("[data-model-change]")).toBeNull();
    rerender(view(plan("football", FOOTBALL, 62.4)));
    expect(marked(container).map((text) => text!.slice(0, 4))).toEqual(["P201", "P202"]);
    const line = container.querySelector("[data-model-change]")!;
    expect(line.textContent).toContain(COPY.modelChangePlayers(COPY.modelNames.football, 2));
    expect(line.textContent).toContain(COPY.modelChangeDifference);
    expect(line.textContent).not.toMatch(AS_A_CHANCE);
    expect(line.textContent).not.toMatch(AS_A_CAVEAT);
  });

  it("raises each changed plate once, by transform only, and counts the difference from zero", () => {
    const { container, rerender } = render(view(plan("current", CURRENT, 60)));
    started = [];
    rerender(view(plan("football", FOOTBALL, 62.4)));
    const plates = started.filter(({ element }) => element.hasAttribute("data-plate"));
    expect(plates.map(({ element }) => element.textContent!.slice(0, 4))).toEqual(["P201", "P202"]);
    for (const { keyframes } of plates)
      for (const frame of keyframes)
        for (const key of Object.keys(frame)) expect(["transform", "offset"]).toContain(key);
    const counter = container.querySelector("[data-model-change] [data-counting-number]")!;
    expect(started.some(({ element }) => element === counter)).toBe(true);
    // A re-render of the same plan moves nothing more.
    const count = started.length;
    rerender(view(plan("football", FOOTBALL, 62.4)));
    expect(started).toHaveLength(count);
  });

  it("marks a player brought onto the bench too, and the line counts the marks", () => {
    const { container, rerender } = render(view(plan("current", CURRENT, 60)));
    // Two new in the eleven, and 203 onto the bench for 94: three marks, three said.
    rerender(view(plan("football", FOOTBALL, 62.4, {}, [91, 92, 93, 203])));
    expect(marked(container).map((text) => text!.slice(0, 4))).toEqual(["P201", "P202", "P203"]);
    expect(container.querySelectorAll("[data-mark='bench'] [data-model-changed]")).toHaveLength(1);
    expect(said(container, 3)).toBe(true);
  });

  it("marks a bench player the new model brings into the eleven, with the same fifteen", () => {
    const { container, rerender } = render(view(plan("current", CURRENT, 60)));
    rerender(view(plan("football", [91, ...CURRENT.slice(1)], 61, {}, [CURRENT[0]!, 92, 93, 94])));
    expect(marked(container).map((text) => text!.slice(0, 3))).toEqual(["P91"]);
    expect(said(container, 1)).toBe(true);
  });

  it("names the mark in each marked plate's text, and nowhere else", () => {
    const { container, rerender } = render(view(plan("current", CURRENT, 60)));
    rerender(view(plan("football", FOOTBALL, 62.4, {}, [91, 92, 93, 203])));
    const plates = [...container.querySelectorAll("[data-plate]")];
    const named = plates.filter((plate) => plate.textContent!.includes(COPY.modelChangedMark));
    expect(named.map((plate) => plate.textContent!.slice(0, 4))).toEqual(["P201", "P202", "P203"]);
    expect(named.every((plate) => plate.closest("[data-model-changed]") !== null)).toBe(true);
  });

  it("marks nothing when a switch of strategy changes the players", () => {
    const { container, rerender } = render(view(plan("current", CURRENT)));
    rerender(view(plan("football", FOOTBALL, 60, { mode: "ortak-koru" })));
    expect(container.querySelectorAll("[data-model-changed]")).toHaveLength(0);
    expect(container.querySelector("[data-model-change]")).toBeNull();
  });

  it("reads the plan shown just before, so a way back through a strategy marks nothing", () => {
    const { container, rerender } = render(view(plan("current", CURRENT)));
    rerender(view(plan("current", FOOTBALL, 60, { mode: "ortak-koru" })));
    rerender(
      view(plan("football", [...FOOTBALL.slice(0, 9), 301, 302], 61, { mode: "ortak-koru" })),
    );
    expect(marked(container).map((text) => text!.slice(0, 4))).toEqual(["P301", "P302"]);
    expect(said(container, 2)).toBe(true);
    rerender(view(plan("football", FOOTBALL, 62)));
    expect(container.querySelectorAll("[data-model-changed]")).toHaveLength(0);
    expect(container.querySelector("[data-model-change]")).toBeNull();
  });

  it("raises the plates again on a switch back and forth", () => {
    const { rerender } = render(view(plan("current", CURRENT, 60)));
    rerender(view(plan("football", FOOTBALL, 62.4)));
    rerender(view(plan("current", CURRENT, 60)));
    started = [];
    rerender(view(plan("football", FOOTBALL, 62.4)));
    const plates = started.filter(({ element }) => element.hasAttribute("data-plate"));
    expect(plates.map(({ element }) => element.textContent!.slice(0, 4))).toEqual(["P201", "P202"]);
  });

  it("says the difference is this week's on a plan of several weeks", () => {
    const { container, rerender } = render(view(plan("current", CURRENT, 60, { window: 3 })));
    rerender(view(plan("football", FOOTBALL, 62.4, { window: 3 })));
    const line = container.querySelector("[data-model-change]")!;
    expect(line.textContent).toContain(COPY.modelChangeDifferenceWeek);
    expect(line.textContent).not.toContain(`${COPY.modelChangeDifference} `);
  });

  it("under reduced motion moves nothing and shows the same marks and line", () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: (query: string) => ({
        matches: query === REDUCED_MOTION_QUERY,
        addEventListener() {},
        removeEventListener() {},
      }),
    });
    const { container, rerender } = render(view(plan("current", CURRENT, 60)));
    started = [];
    rerender(view(plan("football", FOOTBALL, 62.4)));
    expect(started).toEqual([]);
    expect(marked(container)).toHaveLength(2);
    expect(container.querySelector("[data-model-change] [data-counting-number]")!.textContent).toBe(
      "+2,4",
    );
  });
});

function luminance(colour: string): number {
  const channels = [1, 3, 5].map((start) => parseInt(colour.slice(start, start + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

function contrast(one: string, other: string): number {
  const [light, dark] = [luminance(one), luminance(other)].sort((a, b) => b - a);
  return (light! + 0.05) / (dark! + 0.05);
}

describe("the mark's stylesheet", () => {
  const css = readFileSync(join(__dirname, "../components/MemberPitch.module.css"), "utf-8");
  const rule =
    css.match(
      /\.token\[data-model-changed\] \.plate,\n\.benchItem\[data-model-changed\] \.benchName \{([^}]*)\}/,
    )?.[1] ?? "";

  it("is a static ring in the accent with an ink edge, on the pitch and the bench alike", () => {
    expect(rule).toMatch(/outline: 2px solid var\(--color-lime\)/);
    expect(rule).toMatch(/0 0 0 1px var\(--color-text\),\s*0 0 0 4px var\(--color-text\)/);
    expect(rule).not.toMatch(/transition|animation/);
  });

  it("reaches 3:1 on both grass stripes and on the bench's surface", () => {
    const tokens = readFileSync(join(__dirname, "../../../design/tokens.css"), "utf-8");
    const token = (name: string) => tokens.match(new RegExp(`${name}:\\s*(#[0-9a-f]{6});`))![1]!;
    const ink = token("--color-text");
    // The accent meets only the ink edge; the ink edge meets the grass or the surface.
    expect(contrast(token("--color-lime"), ink)).toBeGreaterThanOrEqual(3);
    for (const ground of ["--color-pitch", "--color-pitch-2", "--color-surface", "--color-bg"])
      expect(contrast(ink, token(ground))).toBeGreaterThanOrEqual(3);
  });
});
