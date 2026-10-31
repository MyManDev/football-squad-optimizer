import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OPENING_MS, OPENING_STORAGE_KEY, OpeningMark } from "./OpeningMark";

const cover = () => document.querySelector("[data-opening-mark]");

function preferReducedMotion(reduce: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) => ({ matches: reduce, media: query }) as unknown as MediaQueryList,
  );
}

describe("the brand's opening", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    window.sessionStorage.clear();
    preferReducedMotion(false);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("plays once per tab, hidden from assistive technology, and leaves on its clock", () => {
    render(<OpeningMark />);
    expect(cover()).not.toBeNull();
    expect(cover()).toHaveAttribute("aria-hidden", "true");
    expect(cover()).toHaveTextContent("SquadOpt");
    expect(window.sessionStorage.getItem(OPENING_STORAGE_KEY)).toBe("1");
    act(() => vi.advanceTimersByTime(OPENING_MS));
    expect(cover()).toBeNull();

    cleanup();
    render(<OpeningMark />);
    expect(cover()).toBeNull();
  });

  it("never shows under the reduced-motion preference", () => {
    preferReducedMotion(true);
    render(<OpeningMark />);
    expect(cover()).toBeNull();
  });

  it("draws red on the left and green on the right before the quarter turn", () => {
    render(<OpeningMark />);
    const bars = [...document.querySelectorAll("[data-opening-mark] rect")];
    expect(bars.map((bar) => bar.getAttribute("data-bar"))).toEqual(["out", "in"]);
  });
});
