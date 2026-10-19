import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { countTo, forgetCounts, rememberCount } from "./countMotion";
import { MOTION_MS } from "./motion";

const format = (value: number) => value.toFixed(1);
const motion = { matchMedia: () => ({ matches: false }) as MediaQueryList };
const reduced = { matchMedia: () => ({ matches: true }) as MediaQueryList };

type Fake = {
  animation: Animation;
  setProgress: (progress: number | null) => void;
  finish: () => void;
};

/** An `element.animate` stand-in whose progress the test sets, with the WAAPI events used. */
function fakeAnimate(element: HTMLElement): {
  animate: ReturnType<typeof vi.fn>;
  last: () => Fake;
} {
  let fake: Fake | null = null;
  const animate = vi.fn(() => {
    const listeners = new Map<string, () => void>();
    let progress: number | null = 0;
    let playState: AnimationPlayState = "running";
    const animation = {
      effect: { getComputedTiming: () => ({ progress }) },
      get playState() {
        return playState;
      },
      addEventListener: (type: string, listener: () => void) => listeners.set(type, listener),
      cancel: () => {
        playState = "idle";
        listeners.get("cancel")?.();
      },
    } as unknown as Animation;
    fake = {
      animation,
      setProgress: (value) => {
        progress = value;
      },
      finish: () => {
        playState = "finished";
        progress = null;
        listeners.get("finish")?.();
      },
    };
    return animation;
  });
  Object.defineProperty(element, "animate", { value: animate, configurable: true });
  return { animate, last: () => fake! };
}

let frames: FrameRequestCallback[] = [];
const runFrame = () => {
  const pending = frames;
  frames = [];
  for (const callback of pending) callback(0);
};

beforeEach(() => {
  frames = [];
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.push(callback);
    return frames.length;
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  forgetCounts();
});

describe("countTo", () => {
  it("writes the final value at once under reduced motion, with no animation", () => {
    const element = document.createElement("span");
    const { animate } = fakeAnimate(element);
    expect(countTo(element, 40, 52.5, format, reduced)).toBeNull();
    expect(animate).not.toHaveBeenCalled();
    expect(element.textContent).toBe("52.5");
  });

  it("starts nothing when the value does not change or is not finite", () => {
    const element = document.createElement("span");
    const { animate } = fakeAnimate(element);
    expect(countTo(element, 52.5, 52.5, format, motion)).toBeNull();
    expect(countTo(element, Number.NaN, 52.5, format, motion)).toBeNull();
    expect(countTo(element, 40, Number.POSITIVE_INFINITY, format, motion)).toBeNull();
    expect(animate).not.toHaveBeenCalled();
  });

  it("writes the final value where the browser has no element.animate", () => {
    const element = document.createElement("span");
    expect(countTo(element, 40, 52.5, format, motion)).toBeNull();
    expect(element.textContent).toBe("52.5");
  });

  it("counts on opacity for the data duration and ends on the final value", () => {
    const element = document.createElement("span");
    const { animate, last } = fakeAnimate(element);
    const animation = countTo(element, 40, 50, format, motion);
    expect(animation).not.toBeNull();
    expect(animate).toHaveBeenCalledTimes(1);
    const [keyframes, options] = animate.mock.calls[0]!;
    expect(keyframes).toEqual([{ opacity: 0.6 }, { opacity: 1 }]);
    expect(options).toMatchObject({ duration: MOTION_MS.data });
    expect(Object.keys((keyframes as Keyframe[])[0]!)).toEqual(["opacity"]);
    expect(element.textContent).toBe("40.0");
    last().setProgress(0.5);
    runFrame();
    expect(element.textContent).toBe("45.0");
    last().finish();
    runFrame();
    expect(element.textContent).toBe("50.0");
    expect(frames).toHaveLength(0);
  });

  it("leaves the final value written when the count is cancelled", () => {
    const element = document.createElement("span");
    const { last } = fakeAnimate(element);
    const animation = countTo(element, 40, 50, format, motion)!;
    last().setProgress(0.25);
    runFrame();
    expect(element.textContent).toBe("42.5");
    animation.cancel();
    runFrame();
    expect(element.textContent).toBe("50.0");
  });
});

describe("rememberCount", () => {
  it("returns what a key showed before, and nothing the first time", () => {
    expect(rememberCount("net:1:7", 42)).toBeNull();
    expect(rememberCount("net:1:7", 45)).toBe(42);
    expect(rememberCount("net:2:7", 30)).toBeNull();
    forgetCounts();
    expect(rememberCount("net:1:7", 45)).toBeNull();
  });
});
