/**
 * The model-switch highlight on the member page (#1131): after a switch of prediction model,
 * the players the new plan brings in carry a mark on the pitch and their plates rise once, and
 * a line under the gain strip says how many changed and counts the points difference up from
 * zero. Unchanged players stay as they are; a switch of anything else marks nothing; under
 * reduced motion nothing moves and the marks and the line are the same.
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
): LeagueViewEnvelope<EntryAdvice> {
  return {
    ...EXAMPLE,
    payload: {
      ...EXAMPLE.payload,
      starting_xi: eleven.map(player),
      bench: [91, 92, 93, 94].map((id, i) => ({
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

  it("marks nothing when a switch of strategy changes the players", () => {
    const { container, rerender } = render(view(plan("current", CURRENT)));
    rerender(view(plan("football", FOOTBALL, 60, { mode: "ortak-koru" })));
    expect(container.querySelectorAll("[data-model-changed]")).toHaveLength(0);
    expect(container.querySelector("[data-model-change]")).toBeNull();
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

describe("the mark's stylesheet", () => {
  it("is a static ring in the accent, no motion of its own", () => {
    const css = readFileSync(join(__dirname, "../components/MemberPitch.module.css"), "utf-8");
    const rule = css.match(/\.token\[data-model-changed\] \.plate \{([^}]*)\}/)?.[1] ?? "";
    expect(rule).toMatch(/outline: 2px solid var\(--color-lime\)/);
    expect(rule).not.toMatch(/transition|animation/);
  });
});
