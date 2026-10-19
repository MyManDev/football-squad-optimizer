/**
 * A figure that counts to its new value when its data changes (#1131 step 3).
 *
 * The timing is the Web Animations API's: `element.animate` runs a short opacity change for
 * `motionDuration("data")`, and each frame writes the value at that animation's progress. So
 * the reduced-motion preference, which makes the duration zero, writes the final value at once,
 * from the same place every other motion asks. Only opacity animates; the figures are tabular
 * (`.num`), so the digits change in place and nothing around them moves.
 */
import { MOTION_EASE, motionDuration } from "./motion";

type MediaSource = Parameters<typeof motionDuration>[1];

/** The resting state is fully opaque; the count starts slightly dimmed and settles. */
const COUNT_KEYFRAMES: Keyframe[] = [{ opacity: 0.6 }, { opacity: 1 }];
const COUNT_EASE = `cubic-bezier(${MOTION_EASE.join(", ")})`;

/**
 * Writes `to` into `element`, counting from `from` when there is motion to show.
 *
 * Returns the running animation, or null when the value was written at once: no change, a
 * value that is not finite, reduced motion, or a browser without `element.animate`. Cancelling
 * the animation, or its end, leaves the final value written.
 */
export function countTo(
  element: HTMLElement,
  from: number,
  to: number,
  format: (value: number) => string,
  source?: MediaSource,
): Animation | null {
  const settle = () => {
    element.textContent = format(to);
  };
  const duration = motionDuration("data", source);
  if (
    duration === 0 ||
    from === to ||
    !Number.isFinite(from) ||
    !Number.isFinite(to) ||
    typeof element.animate !== "function"
  ) {
    settle();
    return null;
  }
  const animation = element.animate(COUNT_KEYFRAMES, { duration, easing: COUNT_EASE });
  let done = false;
  const finish = () => {
    done = true;
    settle();
  };
  animation.addEventListener("finish", finish);
  animation.addEventListener("cancel", finish);
  const step = () => {
    if (done) return;
    const progress = animation.effect?.getComputedTiming().progress;
    if (progress === null || progress === undefined) {
      if (animation.playState === "finished") finish();
      else requestAnimationFrame(step);
      return;
    }
    element.textContent = format(from + (to - from) * progress);
    requestAnimationFrame(step);
  };
  element.textContent = format(from);
  requestAnimationFrame(step);
  return animation;
}

/**
 * The last value each counted figure showed, by a key its caller names (a member's entry and
 * the figure), for this page session. A figure is unmounted while its next plan loads, so the
 * value it counts from has to outlive the element.
 */
const lastShown = new Map<string, number>();

/** Records `value` under `key` and returns what that key showed before, or null the first time. */
export function rememberCount(key: string, value: number): number | null {
  const before = lastShown.get(key);
  lastShown.set(key, value);
  return before === undefined ? null : before;
}

/** Clears the record; for tests and for a page that starts over. */
export function forgetCounts(): void {
  lastShown.clear();
}
