import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { figurePaths, POSES } from "../scene/matchFigures";
import { MatchScene } from "./MatchScene";

const ball = (container: HTMLElement) => container.querySelector("svg g[style]");

describe("MatchScene", () => {
  it("is a picture only: hidden from a reader, and nothing in it takes focus or a click", () => {
    const { container } = render(<MatchScene tall={false} arrival="/" />);
    expect(container.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
    expect(container.querySelectorAll("a, button, input, [tabindex], text, title")).toHaveLength(0);
  });

  it("composes a wide scene beside the sidebar and a tall one for a phone", () => {
    const wide = render(<MatchScene tall={false} arrival="/" />);
    expect(wide.container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 1600 1000");
    const tall = render(<MatchScene tall arrival="/" />);
    expect(tall.container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 600 1200");
  });

  it("sends the ball round again when a page arrives, and not on a redraw of the same page", () => {
    const { container, rerender } = render(<MatchScene tall={false} arrival="/a" />);
    const first = ball(container);
    expect(first).not.toBeNull();
    rerender(<MatchScene tall={false} arrival="/a" />);
    expect(ball(container)).toBe(first);
    rerender(<MatchScene tall={false} arrival="/b" />);
    expect(ball(container)).not.toBe(first);
  });
});

describe("the players' figures", () => {
  it.each(Object.entries(POSES))("draws %s as closed shapes with real numbers", (_, pose) => {
    const { near, far, seams, toe, hand } = figurePaths(pose);
    for (const path of [near, far, seams]) {
      expect(path).toMatch(/^M/);
      expect(path).toMatch(/Z$/);
      expect(path).not.toMatch(/NaN|Infinity/);
    }
    expect([...toe, ...hand].every(Number.isFinite)).toBe(true);
  });
});
