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

/** A count in flight, as `countTo` returns it. */
export interface Count {
  /** Whether the count is still writing values. */
  readonly running: boolean;
  /**
   * Stops the count where it is and returns the value on screen. Nothing is written after
   * this, not even by the animation's asynchronous cancel event.
   */
  stop(): number;
}

/**
 * Writes `to` into `element`, counting from `from` when there is motion to show.
 *
 * Returns the count in flight, or null when the value was written at once: no change, a value
 * that is not finite, reduced motion, or a browser without `element.animate`. The count's end,
 * or a cancel from outside, leaves the final value written; `stop` leaves the value on screen.
 */
export function countTo(
  element: HTMLElement,
  from: number,
  to: number,
  format: (value: number) => string,
  source?: MediaSource,
): Count | null {
  const duration = motionDuration("data", source);
  if (
    duration === 0 ||
    from === to ||
    !Number.isFinite(from) ||
    !Number.isFinite(to) ||
    typeof element.animate !== "function"
  ) {
    element.textContent = format(to);
    return null;
  }
  const animation = element.animate(COUNT_KEYFRAMES, { duration, easing: COUNT_EASE });
  let shown = from;
  let done = false;
  const write = (value: number) => {
    shown = value;
    element.textContent = format(value);
  };
  const finish = () => {
    if (done) return;
    done = true;
    write(to);
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
    write(from + (to - from) * progress);
    requestAnimationFrame(step);
  };
  write(from);
  requestAnimationFrame(step);
  return {
    get running() {
      return !done;
    },
    stop() {
      // Superseded: the cancel below must not write the abandoned target.
      done = true;
      animation.cancel();
      return shown;
    },
  };
}

/**
 * The last value each counted figure showed, by a key its caller names (the league, a member's
 * entry and the figure), for this page session. A figure is unmounted while its next plan
 * loads, so the value it counts from has to outlive the element.
 */
const lastShown = new Map<string, number>();

/**
 * Records `value` under `key` and returns what that key showed before, or null the first time.
 * A count that is stopped records the value it left on screen, so the next one starts there.
 */
export function rememberCount(key: string, value: number): number | null {
  const before = lastShown.get(key);
  lastShown.set(key, value);
  return before === undefined ? null : before;
}

/** Clears the record; for tests and for a page that starts over. */
export function forgetCounts(): void {
  lastShown.clear();
}
