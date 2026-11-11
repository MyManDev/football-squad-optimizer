import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MOTION_MS } from "../../design/motion";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import { GoalMomentLayer } from "./GoalMoment";
import { ASSIST_SHOUT, GOAL_SHOUT, MOMENT_TIMING } from "./goalMomentTiming";
import type { BoardMoment } from "./boardMoments";
import type { LiveMoment } from "./liveMoments";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.querySelectorAll("[data-opening-mark]").forEach((cover) => cover.remove());
});

const moment = (overrides: Partial<LiveMoment> = {}): LiveMoment => ({
  key: "1:goal:5",
  kind: "goal",
  size: "big",
  elementId: 5,
  name: "Palmer",
  team: "Chelsea",
  position: "MID",
  count: 1,
  multiplier: 1,
  base: 5,
  points: 5,
  ...overrides,
});

const HAALAND = moment({
  key: "1:goal:9",
  elementId: 9,
  name: "Haaland",
  team: "Man City",
  position: "FWD",
  multiplier: 2,
  base: 4,
  points: 8,
});

function show(items: BoardMoment[], language: "tr" | "en" = "tr", id = 1) {
  const view = (batchId: number) => (
    <LanguageProvider initialLanguage={language}>
      <GoalMomentLayer batch={{ id: batchId, items }} />
    </LanguageProvider>
  );
  const result = render(view(id));
  return { ...result, again: (batchId: number) => result.rerender(view(batchId)) };
}

const board = () => document.querySelector<HTMLElement>("[data-goal-board]");
const digits = () => document.querySelector("[data-goal-points]")?.textContent;
const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms));
const reduceMotion = () =>
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === "(prefers-reduced-motion: reduce)",
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));

describe("the GOL board", () => {
  it("rises with the shout, the scorer and the points, and says it once", () => {
    show([moment()]);
    expect(board()).toHaveAttribute("data-goal-board", "goal");
    expect(board()!.textContent).toContain(GOAL_SHOUT);
    expect(board()!.textContent).toContain("Palmer");
    expect(board()!.textContent).toContain("Chelsea · Orta saha");
    expect(digits()).toBe("+5");
    expect(screen.getByRole("status")).toHaveTextContent("Gol: Palmer, +5 puan");
    expect(screen.getByRole("button", { name: "Kapat" })).toBe(board());
  });

  it("speaks English with the same goal shout and its own assist shout", () => {
    show(
      [moment(), moment({ key: "1:assist:7", kind: "assist", name: "Wirtz", base: 3, points: 3 })],
      "en",
    );
    expect(board()!.textContent).toContain(GOAL_SHOUT);
    expect(board()!.textContent).toContain("Chelsea · Midfielder");
    expect(screen.getByRole("status")).toHaveTextContent("Goal: Palmer, +5 points");
    fireEvent.click(board()!);
    expect(board()!.textContent).toContain(ASSIST_SHOUT.en);
    expect(screen.getByRole("status")).toHaveTextContent("Assist: Wirtz, +3 points");
  });

  it("counts the captain's goal: its points, the armband, then what the member gets", () => {
    vi.useFakeTimers();
    show([HAALAND]);
    expect(digits()).toBe("+4");
    expect(board()!.textContent).toContain("C");
    advance(MOMENT_TIMING.rise + MOTION_MS.data);
    expect(digits()).toBe("×2");
    advance(MOTION_MS.data * 2);
    expect(digits()).toBe("+8");
  });

  it("goes down by itself, then plays the next moment of the read", () => {
    vi.useFakeTimers();
    show([moment(), HAALAND]);
    expect(board()!.textContent).toContain("Palmer");
    expect(board()!.textContent).toContain("1/2");
    advance(MOMENT_TIMING.rise + MOMENT_TIMING.holdGoal);
    expect(board()!.textContent).toContain("Haaland");
    expect(board()!.textContent).toContain("2/2");
    advance(MOMENT_TIMING.rise + MOMENT_TIMING.holdGoal + MOTION_MS.data);
    expect(board()).toBeNull();
  });

  it("goes down at once on a tap or Escape, and the page keeps its focus", () => {
    show([moment(), HAALAND]);
    const before = document.activeElement;
    fireEvent.keyDown(document, { key: "Escape" });
    expect(board()!.textContent).toContain("Haaland");
    fireEvent.click(board()!);
    expect(board()).toBeNull();
    expect(document.activeElement).toBe(before);
  });

  it("raises the board with the assist's own shout, then one LED line for a card", () => {
    vi.useFakeTimers();
    show([
      moment({
        key: "2:assist:7",
        kind: "assist",
        size: "big",
        name: "Wirtz",
        base: 3,
        points: 3,
      }),
      moment({
        key: "2:card:4",
        kind: "card",
        size: "small",
        name: "Rice",
        base: null,
        points: null,
      }),
    ]);
    expect(board()).toHaveAttribute("data-goal-board", "assist");
    expect(board()!.textContent).toContain(ASSIST_SHOUT.tr);
    expect(board()!.textContent).toContain("ASİSSSSSSTTTTT");
    expect(digits()).toBe("+3");
    expect(screen.getByRole("status")).toHaveTextContent("Asist: Wirtz, +3 puan");
    advance(MOMENT_TIMING.rise + MOMENT_TIMING.holdAssist);
    const line = document.querySelector("[data-goal-line]");
    expect(line).toHaveAttribute("data-goal-line", "card");
    expect(line!.textContent).toContain("Kart · Rice");
    advance(MOMENT_TIMING.line);
    expect(document.querySelector("[data-goal-line]")).toBeNull();
  });

  it("raises nothing for a reserve the scorer does not count, and the reserve under the bench boost", () => {
    vi.useFakeTimers();
    show([moment({ size: "small", multiplier: 0, points: null, name: "N.Jackson" })]);
    expect(board()).toBeNull();
    expect(document.querySelector("[data-goal-line]")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("");
    cleanup();
    // Under the bench boost the scorer counts the bench: his goal rises the board.
    show([moment({ multiplier: 1, name: "N.Jackson" })]);
    expect(board()!.textContent).toContain("N.Jackson");
  });

  it("raises the substitution board: the starter off on red, the reserve on on green", () => {
    vi.useFakeTimers();
    show([{ key: "sub:1:4:13", kind: "substitution", size: "big", out: "Saka", in: "Trossard" }]);
    const swap = document.querySelector("[data-goal-board='substitution']")!;
    expect(swap.textContent).toContain("Değişiklik");
    expect(swap.textContent).toContain("Çıkan");
    expect(swap.textContent).toContain("Saka");
    expect(swap.textContent).toContain("Giren");
    expect(swap.textContent).toContain("Trossard");
    expect(screen.getByRole("status")).toHaveTextContent("Değişiklik: Çıkan Saka, Giren Trossard");
    advance(MOMENT_TIMING.rise + MOMENT_TIMING.holdAssist);
    expect(document.querySelector("[data-goal-board='substitution']")).toBeNull();
  });

  it("plays a read once: the same batch again starts nothing", () => {
    const { again } = show([moment()]);
    fireEvent.click(board()!);
    again(1);
    expect(board()).toBeNull();
    again(2);
    expect(board()).not.toBeNull();
  });

  it("waits for the opening cover to go", async () => {
    const cover = document.createElement("div");
    cover.setAttribute("data-opening-mark", "");
    document.body.append(cover);
    show([moment()]);
    expect(board()).toBeNull();
    await act(async () => {
      cover.remove();
    });
    expect(board()).not.toBeNull();
  });
});

describe("what the review asked of it", () => {
  it("keeps one live region from the first draw, so each moment is read out", () => {
    const { rerender } = render(
      <LanguageProvider initialLanguage="tr">
        <GoalMomentLayer batch={null} />
      </LanguageProvider>,
    );
    const region = screen.getByRole("status");
    expect(region).toHaveTextContent("");
    rerender(
      <LanguageProvider initialLanguage="tr">
        <GoalMomentLayer batch={{ id: 1, items: [moment()] }} />
      </LanguageProvider>,
    );
    expect(screen.getByRole("status")).toBe(region);
    expect(region).toHaveTextContent("Gol: Palmer, +5 puan");
  });

  it("shows and sends into the live score what the member receives when closed early", () => {
    const total = document.createElement("span");
    total.setAttribute("data-live-total", "");
    document.body.append(total);
    Object.defineProperty(HTMLElement.prototype, "animate", {
      configurable: true,
      writable: true,
      value: () => ({ finished: new Promise(() => undefined) }) as unknown as Animation,
    });
    try {
      vi.useFakeTimers();
      show([HAALAND]);
      advance(MOMENT_TIMING.rise + MOTION_MS.data);
      expect(digits()).toBe("×2");
      fireEvent.click(board()!);
      expect(digits()).toBe("+8");
      const runner = [...document.body.querySelectorAll("span[aria-hidden='true']")].find(
        (node) => node.parentElement === document.body,
      );
      expect(runner?.textContent).toBe("+8");
    } finally {
      delete (HTMLElement.prototype as Partial<HTMLElement>).animate;
      total.remove();
      document.body
        .querySelectorAll(":scope > span[aria-hidden='true']")
        .forEach((node) => node.remove());
    }
  });

  it("takes a small line away on a tap", () => {
    show([
      moment({
        key: "3:card:4",
        kind: "card",
        size: "small",
        name: "Rice",
        base: null,
        points: null,
      }),
    ]);
    const line = document.querySelector<HTMLElement>("[data-goal-line]")!;
    fireEvent.click(line);
    expect(document.querySelector("[data-goal-line]")).toBeNull();
  });
});

describe("under reduced motion", () => {
  it("names the read's moments on one still line that goes after a while or on its button", () => {
    reduceMotion();
    vi.useFakeTimers();
    const { again } = show([
      HAALAND,
      moment({
        key: "1:card:4",
        kind: "card",
        size: "small",
        name: "Rice",
        points: null,
        base: null,
      }),
    ]);
    expect(board()).toBeNull();
    const still = document.querySelector("[data-goal-still]")!;
    expect(still.textContent).toContain(`${GOAL_SHOUT} · Haaland · +8`);
    expect(still.textContent).toContain("Kart · Rice");
    advance(MOMENT_TIMING.still);
    expect(document.querySelector("[data-goal-still]")).toBeNull();
    again(2);
    fireEvent.click(screen.getByRole("button", { name: "Kapat" }));
    expect(document.querySelector("[data-goal-still]")).toBeNull();
  });
});

describe("its motion", () => {
  it("moves only transform and opacity, for the token durations", () => {
    const calls: { frames: Keyframe[]; duration: number }[] = [];
    // jsdom has no Web Animations; this stands in for it and records each call.
    Object.defineProperty(HTMLElement.prototype, "animate", {
      configurable: true,
      writable: true,
      value(frames: Keyframe[], options: KeyframeAnimationOptions) {
        calls.push({ frames, duration: Number(options.duration) });
        return { finished: new Promise(() => undefined) } as unknown as Animation;
      },
    });
    try {
      vi.useFakeTimers();
      show([HAALAND]);
      advance(MOMENT_TIMING.rise + MOMENT_TIMING.holdGoal + MOTION_MS.data);
    } finally {
      delete (HTMLElement.prototype as Partial<HTMLElement>).animate;
    }
    expect(calls.length).toBeGreaterThan(GOAL_SHOUT.length);
    const allowed = new Set<number>([
      MOMENT_TIMING.rise,
      MOMENT_TIMING.fall,
      MOTION_MS.uiFast,
      MOTION_MS.data,
      MOMENT_TIMING.run,
    ]);
    for (const { frames, duration } of calls) {
      expect(allowed).toContain(duration);
      for (const frame of frames) {
        expect(
          Object.keys(frame).every((key) => ["transform", "opacity", "offset"].includes(key)),
        ).toBe(true);
      }
    }
  });

  it("holds every timing as a multiple of the motion tokens, and no stylesheet motion", () => {
    expect(MOMENT_TIMING.holdGoal % MOTION_MS.data).toBe(0);
    expect(MOMENT_TIMING.letter * 3).toBe(MOTION_MS.uiFast);
    const css = readFileSync(join(__dirname, "GoalMoment.module.css"), "utf-8").replace(
      /\/\*[\s\S]*?\*\//g,
      "",
    );
    expect(css).not.toMatch(/animation|transition|@keyframes/);
  });
});
