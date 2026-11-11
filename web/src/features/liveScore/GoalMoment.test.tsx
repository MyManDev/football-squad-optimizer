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
      <GoalMomentLayer batch={{ id: `live:${batchId}`, items }} />
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
    expect(board()!.textContent).toContain(GOAL_SHOUT.tr);
    expect(board()!.textContent).toContain("Palmer");
    expect(board()!.textContent).toContain("Chelsea · Orta saha");
    expect(digits()).toBe("+5");
    expect(screen.getByRole("status")).toHaveTextContent("Gol: Palmer, +5 puan");
    expect(screen.getByRole("button", { name: "Kapat" })).toBe(board());
  });

  it("speaks English with its own stretched GOAL and ASSIST", () => {
    show(
      [moment(), moment({ key: "1:assist:7", kind: "assist", name: "Wirtz", base: 3, points: 3 })],
      "en",
    );
    expect(board()!.textContent).toContain(GOAL_SHOUT.en);
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
        <GoalMomentLayer batch={{ id: "live:1", items: [moment()] }} />
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

describe("what the second review asked of it", () => {
  it("names a player's two goals of one read as one moment everywhere: board, voice and line", () => {
    show([moment({ count: 2, base: 10, points: 10 })]);
    expect(board()!.textContent).toContain("×2");
    expect(screen.getByRole("status")).toHaveTextContent("Gol ×2: Palmer, +10 puan");
  });

  it("never takes focus, so nothing is lost when it goes", () => {
    show([moment()]);
    expect(board()).toHaveAttribute("tabindex", "-1");
  });

  it("leaves the small line to the eye: the live region says it", () => {
    show([
      moment({
        key: "4:card:4",
        kind: "card",
        size: "small",
        name: "Rice",
        base: null,
        points: null,
      }),
    ]);
    expect(document.querySelector("[data-goal-line]")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Kart: Rice");
  });

  it("waits while a modal dialog is open, and plays when it closes", async () => {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("open", "");
    document.body.append(dialog);
    try {
      show([moment()]);
      expect(board()).toBeNull();
      await act(async () => {
        dialog.removeAttribute("open");
      });
      expect(board()).not.toBeNull();
    } finally {
      dialog.remove();
    }
  });

  it("tells the page when a moment's points have arrived, or will not run there", () => {
    const landed = vi.fn();
    render(
      <LanguageProvider initialLanguage="tr">
        <GoalMomentLayer batch={{ id: "live:1", items: [moment()] }} onLanded={landed} />
      </LanguageProvider>,
    );
    fireEvent.click(board()!);
    expect(landed).toHaveBeenCalledWith(moment().key);
  });
});

describe("what the phone test asked of it", () => {
  const rect = (top: number, bottom: number) =>
    ({
      top,
      bottom,
      left: 0,
      right: 320,
      width: 320,
      height: bottom - top,
      x: 0,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect;
  const top = () => board()!.parentElement!.style.top;

  it("gives way to a drawer or a sheet that opens, and plays the moment again once it closes", async () => {
    const drawer = document.createElement("div");
    document.body.append(drawer);
    try {
      show([moment()]);
      expect(board()).not.toBeNull();
      await act(async () => {
        drawer.setAttribute("aria-modal", "true");
      });
      expect(board()).toBeNull();
      await act(async () => {
        drawer.removeAttribute("aria-modal");
      });
      expect(board()).toHaveAttribute("data-goal-board", "goal");
    } finally {
      drawer.remove();
    }
  });

  it("stands wholly inside a short screen, as a phone on its side", () => {
    vi.stubGlobal("innerHeight", 320);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(224);
    show([moment()]);
    // 320 high: 224 for the board and 12 below it.
    expect(top()).toBe("84px");
  });

  it("keeps the live score's refresh button and total clear while they are in view", () => {
    vi.stubGlobal("innerHeight", 568);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(160);
    const card = document.createElement("div");
    card.setAttribute("data-member-live-score", "");
    const total = document.createElement("span");
    total.setAttribute("data-live-total", "");
    card.append(total);
    document.body.append(card);
    card.getBoundingClientRect = () => rect(216, 560);
    total.getBoundingClientRect = () => rect(270, 300);
    try {
      show([moment()]);
      // Below the total, not across the card's head where 38% down the screen (216) would be.
      expect(top()).toBe("312px");
    } finally {
      card.remove();
    }
  });

  /** A phone on its side: 320 high, the phone bar to 56, a live card with its Yenile and total. */
  function sideways(totalTo: number) {
    vi.stubGlobal("innerHeight", 320);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(143);
    const bar = document.createElement("header");
    bar.setAttribute("data-phone-bar", "");
    bar.getBoundingClientRect = () => rect(0, 56);
    const card = document.createElement("div");
    card.setAttribute("data-member-live-score", "");
    const button = document.createElement("button");
    button.setAttribute("data-live-refresh", "");
    const total = document.createElement("span");
    total.setAttribute("data-live-total", "");
    card.append(button, total);
    document.body.append(bar, card);
    card.getBoundingClientRect = () => rect(100, 400);
    button.getBoundingClientRect = () => rect(112, 156);
    total.getBoundingClientRect = () => rect(totalTo - 30, totalTo);
    return () => {
      bar.remove();
      card.remove();
    };
  }
  const scale = () => board()!.parentElement!.style.transform;

  it("stands smaller in the largest room the head leaves when no place holds it whole", () => {
    // The head from 100 to 200: 20 free above it, 96 below it (212 to 308).
    const remove = sideways(200);
    try {
      show([moment()]);
      expect(top()).toBe("212px");
      expect(scale()).toBe("scale(0.671)");
    } finally {
      remove();
    }
  });

  it("keeps at least the refresh button clear when even half its size has no room", () => {
    // The head from 100 to 250: 46 free below it, under half the board's 143.
    const remove = sideways(250);
    try {
      show([moment()]);
      // The lowest place on the screen (320 - 143 - 12), below the button.
      expect(top()).toBe("165px");
      expect(scale()).toBe("");
    } finally {
      remove();
    }
  });

  it("stands smaller between LIVE's head and its Yenile when neither leaves it room whole", () => {
    // LIVE on a small phone on its side: the head from 80 to 150, Yenile from 260 to 300.
    vi.stubGlobal("innerHeight", 320);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(143);
    const bar = document.createElement("header");
    bar.setAttribute("data-phone-bar", "");
    bar.getBoundingClientRect = () => rect(0, 56);
    const head = document.createElement("section");
    head.setAttribute("data-live-head", "");
    const total = document.createElement("span");
    total.setAttribute("data-live-total", "");
    head.append(total);
    const refresh = document.createElement("button");
    refresh.setAttribute("data-live-refresh", "");
    document.body.append(bar, head, refresh);
    head.getBoundingClientRect = () => rect(80, 150);
    total.getBoundingClientRect = () => rect(110, 150);
    refresh.getBoundingClientRect = () => rect(260, 300);
    try {
      show([moment()]);
      // The 86 between them (162 to 248) holds the board at 0.601 of its size.
      expect(top()).toBe("162px");
      expect(scale()).toBe("scale(0.601)");
    } finally {
      bar.remove();
      head.remove();
      refresh.remove();
    }
  });

  it("stands under half its size at LIVE's top on a small phone on its side, clear of the total", () => {
    // iPhone SE on its side at LIVE's top: the head from 146 to 225, Yenile out of view.
    vi.stubGlobal("innerHeight", 320);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(146);
    const bar = document.createElement("header");
    bar.setAttribute("data-phone-bar", "");
    bar.getBoundingClientRect = () => rect(0, 56);
    const head = document.createElement("section");
    head.setAttribute("data-live-head", "");
    const total = document.createElement("span");
    total.setAttribute("data-live-total", "");
    head.append(total);
    document.body.append(bar, head);
    head.getBoundingClientRect = () => rect(146, 300);
    total.getBoundingClientRect = () => rect(177, 225);
    try {
      show([moment()]);
      // The 71 below the head (237 to 308) holds it at 0.486.
      expect(top()).toBe("237px");
      expect(scale()).toBe("scale(0.486)");
    } finally {
      bar.remove();
      head.remove();
    }
  });

  it("keeps at least the live card's Yenile clear, smaller, where no room clears the head too", () => {
    // The member page on a small phone on its side: the card's head from 105 to 236, its
    // Yenile from 128 to 172; 60 free below the head, under 0.45 of the board's 146.
    vi.stubGlobal("innerHeight", 320);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(146);
    const bar = document.createElement("header");
    bar.setAttribute("data-phone-bar", "");
    bar.getBoundingClientRect = () => rect(0, 56);
    const card = document.createElement("div");
    card.setAttribute("data-member-live-score", "");
    const button = document.createElement("button");
    button.setAttribute("data-live-refresh", "");
    const total = document.createElement("span");
    total.setAttribute("data-live-total", "");
    card.append(button, total);
    document.body.append(bar, card);
    card.getBoundingClientRect = () => rect(105, 400);
    button.getBoundingClientRect = () => rect(128, 172);
    total.getBoundingClientRect = () => rect(212, 236);
    try {
      show([moment()]);
      // Below Yenile, 184 to 308: 0.849 of its size.
      expect(top()).toBe("184px");
      expect(scale()).toBe("scale(0.849)");
    } finally {
      bar.remove();
      card.remove();
    }
  });

  it("fits a name too long for its line, so it breaks only after its hyphen", () => {
    const widths = (name: number) => (element: Element) =>
      element.hasAttribute("data-board-name") ? name : 0;
    const real = window.getComputedStyle;
    vi.spyOn(window, "getComputedStyle").mockImplementation((element, pseudo) =>
      element instanceof HTMLElement && element.hasAttribute("data-board-name")
        ? ({ fontSize: "26px" } as CSSStyleDeclaration)
        : real.call(window, element, pseudo),
    );
    vi.spyOn(Element.prototype, "clientWidth", "get").mockImplementation(function (this: Element) {
      return widths(180)(this);
    });
    // "Abdülkerimoğlu-" alone is 240 wide at 26 px.
    vi.spyOn(Element.prototype, "scrollWidth", "get").mockImplementation(function (this: Element) {
      return widths(240)(this);
    });
    show([moment({ name: "Abdülkerimoğlu-Çağlayangil" })]);
    const name = board()!.querySelector<HTMLElement>("[data-board-name]")!;
    expect(name.style.fontSize).toBe("19px");
    // Its line is free to break again once it is fitted.
    expect(name.style.overflowWrap).toBe("");
  });

  it("fits a captain's name beside the C, which keeps its size", () => {
    const real = window.getComputedStyle;
    vi.spyOn(window, "getComputedStyle").mockImplementation((element, pseudo) =>
      element instanceof HTMLElement && element.hasAttribute("data-board-name")
        ? ({ fontSize: "26px" } as CSSStyleDeclaration)
        : real.call(window, element, pseudo),
    );
    // A 200 px line; the name's word is 220 wide, and the C is 16 wide with 8 before it.
    vi.spyOn(Element.prototype, "clientWidth", "get").mockImplementation(function (this: Element) {
      return this.hasAttribute("data-board-name") ? 200 : 0;
    });
    vi.spyOn(Element.prototype, "scrollWidth", "get").mockImplementation(function (this: Element) {
      return this.hasAttribute("data-board-name") ? 244 : 0;
    });
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.hasAttribute("data-board-chip") ? 16 : 0;
    });
    show([HAALAND]);
    const name = board()!.querySelector<HTMLElement>("[data-board-name]")!;
    // The word takes the 176 the C leaves it: 26 × 176 / 220.
    expect(name.style.fontSize).toBe("20px");
  });

  it("stands again inside the screen when the phone turns while it is up", () => {
    vi.stubGlobal("innerHeight", 800);
    const height = vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(224);
    show([moment()]);
    expect(top()).toBe("304px");
    vi.stubGlobal("innerHeight", 360);
    height.mockReturnValue(224);
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    // 360 high: 224 for the board and 12 below it.
    expect(top()).toBe("124px");
  });
});

describe("what the desktop test asked of it", () => {
  const SWAP: BoardMoment = {
    key: "2:sub:7:15",
    kind: "substitution",
    size: "big",
    out: "Rogers",
    in: "Cherki",
  };
  const CARD = moment({
    key: "3:card:4",
    kind: "card",
    size: "small",
    name: "Tavernier",
    base: null,
    points: null,
  });

  it("tells the page when a substitution's board or a card's line has gone", () => {
    const landed = vi.fn();
    render(
      <LanguageProvider initialLanguage="tr">
        <GoalMomentLayer batch={{ id: "live:1", items: [SWAP, CARD] }} onLanded={landed} />
      </LanguageProvider>,
    );
    fireEvent.click(board()!);
    expect(landed).toHaveBeenCalledWith(SWAP.key);
    fireEvent.click(document.querySelector("[data-goal-line]")!);
    expect(landed).toHaveBeenCalledWith(CARD.key);
  });

  it("takes a card's line and the still line away on Escape", () => {
    show([CARD]);
    expect(document.querySelector("[data-goal-line]")).not.toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.querySelector("[data-goal-line]")).toBeNull();
    cleanup();
    reduceMotion();
    show([moment()]);
    expect(document.querySelector("[data-goal-still]")).not.toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.querySelector("[data-goal-still]")).toBeNull();
  });

  it("lets go of the rise once it is done, so no 3D turn stays on the board or its letters", () => {
    const fills: { frames: Keyframe[]; fill: FillMode | undefined }[] = [];
    Object.defineProperty(HTMLElement.prototype, "animate", {
      configurable: true,
      writable: true,
      value(frames: Keyframe[], options: KeyframeAnimationOptions) {
        fills.push({ frames, fill: options.fill });
        return { finished: new Promise(() => undefined) } as unknown as Animation;
      },
    });
    try {
      show([HAALAND]);
    } finally {
      delete (HTMLElement.prototype as Partial<HTMLElement>).animate;
    }
    const rise = fills.find(
      ({ frames }) => frames[0]?.transform === "perspective(700px) rotateX(-90deg)",
    );
    expect(rise?.fill).toBe("backwards");
    const letters = fills.filter(
      ({ frames }) => frames.length === 2 && frames[0]?.opacity === 0 && !frames[0]?.transform,
    );
    expect(letters.length).toBe(GOAL_SHOUT.tr.length);
    expect(letters.every(({ fill }) => fill === "backwards")).toBe(true);
  });

  it("stands over the page's own column beside a sidebar, not the middle of the window", () => {
    vi.stubGlobal("innerWidth", 1280);
    const main = document.createElement("main");
    main.id = "main";
    document.body.append(main);
    main.getBoundingClientRect = () =>
      ({
        top: 0,
        bottom: 800,
        left: 240,
        right: 1280,
        width: 1040,
        height: 800,
        x: 240,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect;
    try {
      show([moment()]);
      const place = board()!.parentElement!;
      expect(place.style.left).toBe("252px");
      expect(place.style.right).toBe("12px");
    } finally {
      main.remove();
    }
  });
});

describe("what the last review asked of it", () => {
  type Shown = { id: string; items: BoardMoment[] } | null;
  const view = (batch: Shown, source: string, landed: (key: string) => void = () => undefined) => (
    <LanguageProvider initialLanguage="tr">
      <GoalMomentLayer batch={batch} source={source} onLanded={landed} />
    </LanguageProvider>
  );
  const still = () => document.querySelector("[data-goal-still]");
  const rect = (top: number, bottom: number, left = 0, right = 320) =>
    ({
      top,
      bottom,
      left,
      right,
      width: right - left,
      height: bottom - top,
      x: left,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect;

  it("plays a batch once, whichever stream the page shows in between", () => {
    const live = { id: "live:1", items: [moment({ key: "1:goal:5" })] };
    const { rerender } = render(view(live, "live"));
    fireEvent.click(board()!);
    expect(board()).toBeNull();
    rerender(view({ id: "replay:1", items: [moment({ key: "r1:goal:5" })] }, "replay"));
    expect(board()).not.toBeNull();
    fireEvent.click(board()!);
    // Back to the real reads: their last batch has played and does not play again.
    rerender(view(live, "live"));
    expect(board()).toBeNull();
  });

  it("drops the replay's queued moments once the page leaves the replay, and says so", () => {
    const landed = vi.fn();
    const replay = {
      id: "replay:1",
      items: [moment({ key: "r:a" }), moment({ key: "r:b", name: "Saka" })],
    };
    const { rerender } = render(view(replay, "replay", landed));
    expect(board()).not.toBeNull();
    rerender(view(null, "live", landed));
    expect(board()).toBeNull();
    expect(landed).toHaveBeenCalledWith("r:a");
    expect(landed).toHaveBeenCalledWith("r:b");
  });

  it("gives focus back where it was when a tap or a screen reader put it on the board", () => {
    const input = document.createElement("input");
    document.body.append(input);
    try {
      input.focus();
      show([moment()]);
      board()!.focus();
      expect(document.activeElement).toBe(board());
      fireEvent.click(board()!);
      expect(document.activeElement).toBe(input);
      cleanup();
      reduceMotion();
      input.focus();
      show([moment()]);
      const close = still()!.querySelector("button")!;
      close.focus();
      fireEvent.click(close);
      expect(still()).toBeNull();
      expect(document.activeElement).toBe(input);
    } finally {
      input.remove();
    }
  });

  it("fits its words and stands again when the column changes, keeping nothing of before", () => {
    vi.stubGlobal("innerWidth", 1280);
    const main = document.createElement("main");
    main.id = "main";
    document.body.append(main);
    let left = 240;
    main.getBoundingClientRect = () => rect(0, 800, left, 1280);
    try {
      show([moment()]);
      const place = board()!.parentElement!;
      expect(place.style.left).toBe("252px");
      const shout = board()!.firstElementChild!.firstElementChild as HTMLElement;
      shout.style.fontSize = "99px";
      // The sidebar closes, or the phone turns: the board is fitted and placed afresh.
      left = 0;
      act(() => {
        window.dispatchEvent(new Event("resize"));
      });
      expect(place.style.left).toBe("");
      expect(shout.style.fontSize).toBe("");
    } finally {
      main.remove();
    }
  });

  it("stands smaller below the bar and the pinned strip on a screen too short for it", () => {
    vi.stubGlobal("innerHeight", 320);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(260);
    const bar = document.createElement("header");
    bar.setAttribute("data-phone-bar", "");
    bar.getBoundingClientRect = () => rect(0, 56);
    const sections = document.createElement("div");
    sections.setAttribute("data-shown", "");
    const strip = document.createElement("nav");
    strip.setAttribute("data-pinned-strip", "");
    strip.getBoundingClientRect = () => rect(56, 96);
    sections.append(strip);
    document.body.append(bar, sections);
    try {
      show([moment()]);
      const place = board()!.parentElement!;
      // 320 high: 108 under the bar and the strip, 12 below; 200 of room for 260.
      expect(place.style.top).toBe("108px");
      expect(place.style.transform).toBe("scale(0.769)");
    } finally {
      bar.remove();
      sections.remove();
    }
  });

  it("says a moment once, though a panel holds it back and it plays again", async () => {
    const drawer = document.createElement("div");
    document.body.append(drawer);
    try {
      show([moment()]);
      const status = screen.getByRole("status");
      const said = "Gol: Palmer, +5 puan";
      expect(status).toHaveTextContent(said);
      await act(async () => {
        drawer.setAttribute("aria-modal", "true");
      });
      expect(board()).toBeNull();
      // The region keeps its words: nothing new to say, so nothing is said again.
      expect(status).toHaveTextContent(said);
      await act(async () => {
        drawer.removeAttribute("aria-modal");
      });
      expect(board()).not.toBeNull();
      expect(status).toHaveTextContent(said);
    } finally {
      drawer.remove();
    }
  });

  it("keeps a refresh button outside the score's head clear too, as LIVE's under the rival", () => {
    vi.stubGlobal("innerHeight", 844);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(160);
    const headBox = document.createElement("section");
    headBox.setAttribute("data-live-head", "");
    const total = document.createElement("span");
    total.setAttribute("data-live-total", "");
    headBox.append(total);
    const refresh = document.createElement("button");
    refresh.setAttribute("data-live-refresh", "");
    document.body.append(headBox, refresh);
    headBox.getBoundingClientRect = () => rect(80, 220);
    total.getBoundingClientRect = () => rect(150, 200);
    refresh.getBoundingClientRect = () => rect(330, 374);
    try {
      show([moment()]);
      // 38% down (321) would stand over the button: the board goes below it.
      expect(board()!.parentElement!.style.top).toBe("386px");
    } finally {
      headBox.remove();
      refresh.remove();
    }
  });

  describe("under reduced motion", () => {
    it("adds a new read to the still line, and a read with nothing to show leaves it", () => {
      reduceMotion();
      const first = { id: "live:1", items: [moment({ key: "1:goal:5" })] };
      const { rerender } = render(view(first, "live"));
      expect(still()).toHaveTextContent("Palmer");
      // A reserve the scorer does not count: nothing to show.
      const reserve = moment({ key: "2:goal:9", name: "Cherki", multiplier: 0, points: null });
      rerender(view({ id: "live:2", items: [reserve] }, "live"));
      expect(still()).toHaveTextContent("Palmer");
      expect(still()).not.toHaveTextContent("Cherki");
      rerender(
        view({ id: "live:3", items: [moment({ key: "3:goal:9", name: "Haaland" })] }, "live"),
      );
      expect(still()).toHaveTextContent("Palmer");
      expect(still()).toHaveTextContent("Haaland");
    });

    it("turns the queued moments into the still line when it is turned on, and says so", () => {
      const landed = vi.fn();
      const batch = {
        id: "live:1",
        items: [moment({ key: "a" }), moment({ key: "b", name: "Saka" })],
      };
      const { rerender } = render(view(batch, "live", landed));
      expect(board()).not.toBeNull();
      reduceMotion();
      // The page draws again when the setting changes.
      rerender(view(batch, "live", landed));
      expect(board()).toBeNull();
      expect(still()).toHaveTextContent("Palmer");
      expect(still()).toHaveTextContent("Saka");
      expect(landed).toHaveBeenCalledWith("a");
      expect(landed).toHaveBeenCalledWith("b");
    });
  });
});

describe("what the review of the last round asked of it", () => {
  type Shown = { id: string; items: BoardMoment[] } | null;
  const view = (batch: Shown, source: string, landed: (key: string) => void = () => undefined) => (
    <LanguageProvider initialLanguage="tr">
      <GoalMomentLayer batch={batch} source={source} onLanded={landed} />
    </LanguageProvider>
  );
  const still = () => document.querySelector("[data-goal-still]");
  const status = () => screen.getByRole("status");

  it("says only the moments a read adds to the still line, never the ones said before", () => {
    reduceMotion();
    const { rerender } = render(
      view({ id: "live:1", items: [moment({ key: "1:goal:5" })] }, "live"),
    );
    expect(status()).toHaveTextContent("Gol: Palmer, +5 puan");
    rerender(view({ id: "live:2", items: [moment({ key: "2:goal:9", name: "Haaland" })] }, "live"));
    expect(still()).toHaveTextContent("Palmer");
    expect(status()).toHaveTextContent("Gol: Haaland, +5 puan");
    expect(status()).not.toHaveTextContent("Palmer");
  });

  it("does not say the still line again when a panel over it closes", async () => {
    reduceMotion();
    const drawer = document.createElement("div");
    document.body.append(drawer);
    try {
      show([moment()]);
      const said = "Gol: Palmer, +5 puan";
      expect(status()).toHaveTextContent(said);
      await act(async () => {
        drawer.setAttribute("aria-modal", "true");
      });
      expect(still()).toBeNull();
      expect(status()).toHaveTextContent(said);
      await act(async () => {
        drawer.removeAttribute("aria-modal");
      });
      expect(still()).not.toBeNull();
      expect(status()).toHaveTextContent(said);
    } finally {
      drawer.remove();
    }
  });

  it("gives focus to the live score's heading, not the page's title above it, when it was nowhere", () => {
    reduceMotion();
    // The member page: its h1 comes before the live score's heading in the document.
    const main = document.createElement("main");
    const title = document.createElement("h1");
    title.textContent = "Kepazesaray";
    const card = document.createElement("div");
    card.setAttribute("data-member-live-score", "");
    const heading = document.createElement("h2");
    heading.textContent = "11. hafta puanın";
    card.append(heading);
    main.append(title, card);
    document.body.append(main);
    try {
      (document.activeElement as HTMLElement | null)?.blur();
      show([moment()]);
      const close = still()!.querySelector("button")!;
      close.focus();
      fireEvent.click(close);
      expect(still()).toBeNull();
      expect(document.activeElement).toBe(heading);
    } finally {
      main.remove();
    }
  });

  it("lets a board that falls after the page changed stream take away only its own moment", async () => {
    // Each animation ends only when the test says so.
    const runs: { frames: Keyframe[]; end: () => void }[] = [];
    Object.defineProperty(HTMLElement.prototype, "animate", {
      configurable: true,
      writable: true,
      value(frames: Keyframe[]) {
        let end: () => void = () => undefined;
        const finished = new Promise<void>((resolve) => {
          end = () => resolve();
        });
        runs.push({ frames, end });
        return { finished } as unknown as Animation;
      },
    });
    try {
      const { rerender } = render(
        view({ id: "live:1", items: [moment({ key: "live-a" })] }, "live"),
      );
      fireEvent.click(board()!);
      const fall = runs.find(
        (run) => run.frames[0]?.transform === "perspective(700px) rotateX(0deg)",
      );
      expect(fall).toBeDefined();
      // While it falls, the page turns to the replay: its first moment is the queue's head now.
      rerender(
        view({ id: "replay:1", items: [moment({ key: "replay-a", name: "Saka" })] }, "replay"),
      );
      expect(board()).toHaveTextContent("Saka");
      await act(async () => {
        fall!.end();
      });
      expect(board()).toHaveTextContent("Saka");
    } finally {
      delete (HTMLElement.prototype as Partial<HTMLElement>).animate;
    }
  });

  it("is fitted and placed again when the page's column changes size (ResizeObserver)", () => {
    const watchers: (() => void)[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          watchers.push(callback);
        }
        observe() {}
        disconnect() {}
      },
    );
    vi.stubGlobal("innerWidth", 1280);
    const main = document.createElement("main");
    main.id = "main";
    document.body.append(main);
    let left = 240;
    main.getBoundingClientRect = () =>
      ({
        top: 0,
        bottom: 800,
        left,
        right: 1280,
        width: 1280 - left,
        height: 800,
        x: left,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect;
    try {
      show([moment()]);
      const place = board()!.parentElement!;
      expect(place.style.left).toBe("252px");
      const shout = board()!.firstElementChild!.firstElementChild as HTMLElement;
      shout.style.fontSize = "99px";
      // The sidebar closes: no window resize, only the column's own.
      left = 0;
      act(() => {
        for (const watcher of watchers) watcher();
      });
      expect(place.style.left).toBe("");
      expect(shout.style.fontSize).toBe("");
    } finally {
      main.remove();
    }
  });

  /** A wide screen whose page column starts at `left` (a sidebar beside it), as `move` sets it. */
  function column(start: number) {
    vi.stubGlobal("innerWidth", 1280);
    const main = document.createElement("main");
    main.id = "main";
    document.body.append(main);
    let left = start;
    main.getBoundingClientRect = () =>
      ({
        top: 0,
        bottom: 800,
        left,
        right: 1280,
        width: 1280 - left,
        height: 800,
        x: left,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect;
    return {
      move: (to: number) => {
        left = to;
      },
      remove: () => main.remove(),
    };
  }

  it("stands again when a transition on the page ends, as the sidebar opening moves the column", () => {
    const page = column(72);
    try {
      show([moment()]);
      const place = board()!.parentElement!;
      expect(place.style.left).toBe("84px");
      // The sidebar opens over its transition: no resize, the column moved when it ended.
      page.move(264);
      act(() => {
        document.dispatchEvent(new Event("transitionend"));
      });
      expect(place.style.left).toBe("276px");
    } finally {
      page.remove();
    }
  });

  it("lays a card's line over the page's own column, and again when the column moves", () => {
    const page = column(240);
    const card = moment({
      key: "3:card:4",
      kind: "card",
      size: "small",
      name: "Tavernier",
      base: null,
      points: null,
    });
    try {
      render(view({ id: "live:1", items: [card] }, "live"));
      const line = document.querySelector<HTMLElement>("[data-goal-line]")!;
      expect(line.style.left).toBe("252px");
      expect(line.style.right).toBe("12px");
      page.move(0);
      act(() => {
        window.dispatchEvent(new Event("resize"));
      });
      expect(line.style.left).toBe("");
    } finally {
      page.remove();
    }
  });

  it("runs no points into the total for a stream that brings none, as the replay", () => {
    const total = document.createElement("span");
    total.setAttribute("data-live-total", "");
    document.body.append(total);
    // Motions that never end: a points chip run into the total would stay on the page.
    Object.defineProperty(Element.prototype, "animate", {
      configurable: true,
      writable: true,
      value: () =>
        ({ finished: new Promise(() => undefined), cancel() {} }) as unknown as Animation,
    });
    try {
      const landed = vi.fn();
      render(
        <LanguageProvider initialLanguage="tr">
          <GoalMomentLayer
            batch={{ id: "replay:1", items: [moment()] }}
            source="replay"
            scoring={false}
            onLanded={landed}
          />
        </LanguageProvider>,
      );
      fireEvent.click(board()!);
      expect(landed).toHaveBeenCalledWith(moment().key);
      expect(document.querySelector("body > span[aria-hidden='true']")).toBeNull();
    } finally {
      delete (Element.prototype as { animate?: unknown }).animate;
      total.remove();
    }
  });
});

describe("under reduced motion", () => {
  it("goes on a tap anywhere on the still line", () => {
    reduceMotion();
    show([moment()]);
    fireEvent.click(document.querySelector("[data-goal-still]")!);
    expect(document.querySelector("[data-goal-still]")).toBeNull();
  });

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
    expect(still.textContent).toContain(`${GOAL_SHOUT.tr} · Haaland · +8`);
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
    expect(calls.length).toBeGreaterThan(GOAL_SHOUT.tr.length);
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
