import { cleanup, render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { usePitchMovement } from "./usePitchMovement";

let positions: Record<string, [number, number]>;
let started: { id: string; frames: Keyframe[]; cancel: ReturnType<typeof vi.fn> }[];
let width: number;

beforeEach(() => {
  width = 600;
  positions = { "1": [10, 20], "2": [100, 80] };
  started = [];
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
    this: HTMLElement,
  ) {
    const [left, top] = positions[this.dataset.playerMotion ?? ""] ?? [0, 0];
    return {
      left,
      top,
      width,
      height: 44,
      x: left,
      y: top,
      right: left + width,
      bottom: top + 44,
      toJSON() {},
    };
  });
  Object.defineProperty(Element.prototype, "animate", {
    configurable: true,
    value(this: HTMLElement, frames: Keyframe[]) {
      const cancel = vi.fn();
      started.push({ id: this.dataset.playerMotion!, frames, cancel });
      return { cancel };
    },
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete (Element.prototype as { animate?: unknown }).animate;
  delete (window as { matchMedia?: unknown }).matchMedia;
});

function Pitch({
  plan,
  context = "member:week:capture",
  visible = true,
  planned = true,
}: {
  plan: string;
  context?: string;
  visible?: boolean;
  planned?: boolean;
}) {
  const field = useRef<HTMLDivElement>(null);
  usePitchMovement(field, context, plan, visible, planned);
  return (
    <div ref={field}>
      <div data-player-motion="1" />
      <div data-player-motion="2" />
    </div>
  );
}

it("moves a retained player from their old position only when a different plan is shown", () => {
  const { rerender } = render(<Pitch plan="first" />);
  expect(started).toHaveLength(0);
  positions["1"] = [40, 70];
  rerender(<Pitch plan="second" />);
  expect(started).toHaveLength(1);
  expect(started[0]).toMatchObject({
    id: "1",
    frames: [{ transform: "translate(-30px, -50px)" }, { transform: "translate(0px, 0px)" }],
  });
  rerender(<Pitch plan="second" />);
  expect(started).toHaveLength(1);
});

it("never carries another member, week or capture's position into the plan", () => {
  const { rerender } = render(<Pitch plan="first" />);
  positions["1"] = [40, 70];
  rerender(<Pitch plan="second" context="other:capture" />);
  expect(started).toHaveLength(0);
});

it("keeps the first loaded plan still and moves a later answer from the squad actually on screen", () => {
  const { rerender } = render(<Pitch plan="held" planned={false} />);
  positions["1"] = [40, 70];
  rerender(<Pitch plan="first" />);
  expect(started).toHaveLength(0);
  positions["1"] = [10, 20];
  rerender(<Pitch plan="held" planned={false} />);
  expect(started).toHaveLength(0);
  positions["1"] = [80, 90];
  rerender(<Pitch plan="second" />);
  expect(started[0]!.frames[0]).toEqual({ transform: "translate(-70px, -70px)" });
});

it("keeps the final layout immediate under reduced motion", () => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({ matches: true }),
  });
  const { rerender, container } = render(<Pitch plan="first" />);
  positions["1"] = [40, 70];
  rerender(<Pitch plan="second" />);
  expect(started).toHaveLength(0);
  expect(container.querySelector<HTMLElement>("[data-player-motion='1']")!.style.transform).toBe(
    "",
  );
});

it("does not animate a resize or reopening the pitch from the list", () => {
  const { rerender } = render(<Pitch plan="first" />);
  width = 350;
  positions["1"] = [40, 70];
  rerender(<Pitch plan="second" />);
  rerender(<Pitch plan="second" visible={false} />);
  positions["1"] = [200, 80];
  rerender(<Pitch plan="third" />);
  expect(started).toHaveLength(0);
});

it("cancels an interrupted transition when another plan arrives and on unmount", () => {
  const { rerender, unmount } = render(<Pitch plan="first" />);
  positions["1"] = [40, 70];
  rerender(<Pitch plan="second" />);
  positions["1"] = [20, 50];
  rerender(<Pitch plan="third" />);
  expect(started[0]!.cancel).toHaveBeenCalledOnce();
  unmount();
  expect(started[1]!.cancel).toHaveBeenCalledOnce();
});
