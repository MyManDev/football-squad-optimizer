import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { CountingNumber } from "./CountingNumber";
import { points } from "../lib/format";
import { forgetCounts } from "./countMotion";

const tr = (value: number) => value.toFixed(1).replace(".", ",");
const en = (value: number) => value.toFixed(1);

type FakeAnimation = {
  /** The eased progress the next frame reads. */
  progress: number | null;
  cancelled: boolean;
  finish: () => void;
};

let animate: ReturnType<typeof vi.fn>;
let animations: FakeAnimation[] = [];
let frames: FrameRequestCallback[] = [];
// Animation events wait here, as a browser dispatches them after the call that caused them.
let events: (() => void)[] = [];
let reduceMotion = false;

const runFrame = () => {
  const pending = frames;
  frames = [];
  for (const callback of pending) callback(0);
};
const dispatchEvents = () => {
  const pending = events;
  events = [];
  for (const event of pending) event();
};

beforeEach(() => {
  reduceMotion = false;
  animations = [];
  frames = [];
  events = [];
  vi.stubGlobal("matchMedia", () => ({ matches: reduceMotion }) as MediaQueryList);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.push(callback);
    return frames.length;
  });
  animate = vi.fn(() => {
    const listeners = new Map<string, () => void>();
    let playState: AnimationPlayState = "running";
    const fake: FakeAnimation = {
      progress: 0,
      cancelled: false,
      finish: () => {
        playState = "finished";
        fake.progress = null;
        events.push(() => listeners.get("finish")?.());
      },
    };
    animations.push(fake);
    return {
      effect: { getComputedTiming: () => ({ progress: fake.progress }) },
      get playState() {
        return playState;
      },
      addEventListener: (type: string, listener: () => void) => listeners.set(type, listener),
      cancel: () => {
        fake.cancelled = true;
        playState = "idle";
        events.push(() => listeners.get("cancel")?.());
      },
    };
  });
  Object.defineProperty(HTMLElement.prototype, "animate", { value: animate, configurable: true });
});

afterEach(() => {
  cleanup();
  forgetCounts();
  vi.unstubAllGlobals();
  delete (HTMLElement.prototype as { animate?: unknown }).animate;
});

const figure = (container: HTMLElement) =>
  container.querySelector("[data-counting-number]") as HTMLElement;

it("shows the first value as it is and does not count", () => {
  const { container } = render(<CountingNumber countKey="net:1:7" value={42.5} format={en} />);
  expect(figure(container).textContent).toBe("42.5");
  expect(animate).not.toHaveBeenCalled();
});

it("starts nothing when a re-render keeps the value", () => {
  const { container, rerender } = render(
    <CountingNumber countKey="net:1:7" value={42.5} format={en} />,
  );
  rerender(<CountingNumber countKey="net:1:7" value={42.5} format={(value) => en(value)} />);
  expect(animate).not.toHaveBeenCalled();
  expect(figure(container).textContent).toBe("42.5");
});

it("counts once when the value changes", () => {
  const { container, rerender } = render(
    <CountingNumber countKey="net:1:7" value={42.5} format={en} />,
  );
  rerender(<CountingNumber countKey="net:1:7" value={47} format={en} />);
  expect(animate).toHaveBeenCalledTimes(1);
  expect(figure(container).textContent).toBe("42.5");
  rerender(<CountingNumber countKey="net:1:7" value={47} format={en} />);
  expect(animate).toHaveBeenCalledTimes(1);
});

it("counts from the last value a remounted figure showed under the same key", () => {
  const first = render(<CountingNumber countKey="net:1:7" value={42.5} format={en} />);
  first.unmount();
  render(<CountingNumber countKey="net:1:7" value={47} format={en} />);
  expect(animate).toHaveBeenCalledTimes(1);
  cleanup();
  render(<CountingNumber countKey="net:2:7" value={30} format={en} />);
  expect(animate).toHaveBeenCalledTimes(1);
});

it("rewrites the same value in a new language without counting", () => {
  const { container, rerender } = render(
    <CountingNumber countKey="net:1:7" value={42.5} format={en} />,
  );
  rerender(<CountingNumber countKey="net:1:7" value={42.5} format={tr} />);
  expect(animate).not.toHaveBeenCalled();
  expect(figure(container).textContent).toBe("42,5");
});

it("writes a new value at once under reduced motion", () => {
  reduceMotion = true;
  const { container, rerender } = render(
    <CountingNumber countKey="net:1:7" value={42.5} format={en} />,
  );
  rerender(<CountingNumber countKey="net:1:7" value={47} format={en} />);
  expect(animate).not.toHaveBeenCalled();
  expect(figure(container).textContent).toBe("47.0");
});

it("starts an interrupted count from the number on screen, not the target it left", () => {
  const { container, rerender } = render(
    <CountingNumber countKey="net:1:1:7" value={40} format={en} />,
  );
  rerender(<CountingNumber countKey="net:1:1:7" value={50} format={en} />);
  animations[0]!.progress = 0.3;
  runFrame();
  expect(figure(container).textContent).toBe("43.0");

  rerender(<CountingNumber countKey="net:1:1:7" value={60} format={en} />);
  expect(animations[0]!.cancelled).toBe(true);
  expect(animate).toHaveBeenCalledTimes(2);
  expect(figure(container).textContent).toBe("43.0");
  // The old count's cancel event arrives later and writes nothing.
  dispatchEvents();
  runFrame();
  expect(figure(container).textContent).toBe("43.0");

  animations[1]!.progress = 0.5;
  runFrame();
  expect(figure(container).textContent).toBe("51.5");
  animations[1]!.finish();
  dispatchEvents();
  expect(figure(container).textContent).toBe("60.0");
});

it("writes nothing into a figure unmounted mid-count, and its next count starts there", () => {
  const { container, rerender, unmount } = render(
    <CountingNumber countKey="net:1:1:7" value={40} format={en} />,
  );
  rerender(<CountingNumber countKey="net:1:1:7" value={50} format={en} />);
  const shown = figure(container);
  animations[0]!.progress = 0.3;
  runFrame();
  unmount();
  dispatchEvents();
  runFrame();
  expect(shown.textContent).toBe("43.0");
  expect(animations[0]!.cancelled).toBe(true);

  const next = render(<CountingNumber countKey="net:1:1:7" value={50} format={en} />);
  expect(animate).toHaveBeenCalledTimes(2);
  expect(figure(next.container).textContent).toBe("43.0");
});

it("carries a count on in a new language and ends on that language's value", () => {
  const { container, rerender } = render(
    <CountingNumber countKey="net:1:1:7" value={40} format={en} />,
  );
  rerender(<CountingNumber countKey="net:1:1:7" value={50} format={en} />);
  animations[0]!.progress = 0.3;
  runFrame();
  rerender(<CountingNumber countKey="net:1:1:7" value={50} format={tr} />);
  expect(animate).toHaveBeenCalledTimes(1);
  expect(animations[0]!.cancelled).toBe(false);
  animations[0]!.progress = 0.6;
  runFrame();
  expect(figure(container).textContent).toBe("46,0");
  animations[0]!.finish();
  dispatchEvents();
  runFrame();
  expect(figure(container).textContent).toBe("50,0");
  expect(frames).toHaveLength(0);
});

it("formats zero and negative values, and a count across zero ends on its value", () => {
  const local = (value: number) => points(value, 1, "tr-TR");
  const { container, rerender } = render(
    <CountingNumber countKey="net:1:1:7" value={0} format={local} />,
  );
  expect(figure(container).textContent).toBe("0,0");
  rerender(<CountingNumber countKey="net:1:1:7" value={-3.3} format={local} />);
  animations[0]!.finish();
  dispatchEvents();
  expect(figure(container).textContent).toBe("-3,3");
  rerender(<CountingNumber countKey="net:1:1:7" value={2} format={local} />);
  expect(figure(container).textContent).toBe("-3,3");
  animations[1]!.progress = 0.4;
  runFrame();
  expect(figure(container).textContent).toBe("-1,2");
  animations[1]!.progress = 0.8;
  runFrame();
  expect(figure(container).textContent).toBe("0,9");
  animations[1]!.finish();
  dispatchEvents();
  expect(figure(container).textContent).toBe("2,0");
});
