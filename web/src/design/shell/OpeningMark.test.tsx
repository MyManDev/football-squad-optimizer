import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OPENING_LEAVE_MS, OPENING_MS, OPENING_STORAGE_KEY, OpeningMark } from "./OpeningMark";

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
    expect(cover()).toHaveTextContent("MyManDev");
    expect(cover()).toHaveTextContent("Still Building");
    expect(window.sessionStorage.getItem(OPENING_STORAGE_KEY)).toBe("1");
    act(() => vi.advanceTimersByTime(OPENING_MS));
    expect(cover()).not.toBeNull();
    act(() => vi.advanceTimersByTime(OPENING_LEAVE_MS - OPENING_MS));
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

  it("dismisses on a click without sending the click to its parent", () => {
    const click = vi.fn();
    render(
      <div onClick={click}>
        <OpeningMark />
      </div>,
    );
    fireEvent.click(cover()!);
    expect(cover()).toBeNull();
    expect(click).not.toHaveBeenCalled();
  });

  it("dismisses on Tab without preventing the page's focus navigation", () => {
    render(<OpeningMark />);
    expect(fireEvent.keyDown(document, { key: "Tab" })).toBe(true);
    expect(cover()).toBeNull();
  });

  it.each(["Enter", " "])("preserves %j on a focused control while dismissing", (key) => {
    const click = vi.fn();
    const { getByRole } = render(
      <>
        <OpeningMark />
        <button onKeyDown={click}>Open</button>
      </>,
    );
    const button = getByRole("button");
    button.focus();
    expect(fireEvent.keyDown(button, { key })).toBe(true);
    expect(cover()).toBeNull();
    expect(click).toHaveBeenCalledOnce();
    expect(button).toHaveFocus();
  });

  it("reveals a focused field without dropping its first typed character", () => {
    const typed = vi.fn();
    const { getByRole } = render(
      <>
        <OpeningMark />
        <input onKeyDown={typed} />
      </>,
    );
    expect(fireEvent.keyDown(getByRole("textbox"), { key: "1" })).toBe(true);
    expect(typed).toHaveBeenCalledOnce();
    expect(cover()).toBeNull();
  });

  it("reveals the page when a field is filled without keyboard events", () => {
    const { getByRole } = render(
      <>
        <OpeningMark />
        <input />
      </>,
    );
    fireEvent.input(getByRole("textbox"), { target: { value: "123" } });
    expect(cover()).toBeNull();
  });

  it("draws red on the left and green on the right before the quarter turn", () => {
    render(<OpeningMark />);
    const bars = [...document.querySelectorAll("[data-opening-mark] rect")];
    expect(bars.map((bar) => bar.getAttribute("data-bar"))).toEqual(["out", "in"]);
  });
});
