/**
 * The member pages' motion rules (#1136), for the places that time a change in script.
 *
 * The durations and the easing are the `--motion-*` tokens of tokens.css, mirrored here and
 * held equal to them by motion.test.ts, so a stylesheet and a script never disagree. Buttons,
 * cards and icons take `uiFast` or `ui` (150 to 250 ms); the pitch and data take `data` (300 to
 * 500 ms). Page and panel movement have their own gentler timing (#1319). Under the
 * reduced-motion preference every duration is zero and each change is
 * instant; `motionDuration` is the one place a script asks for that.
 */

export const MOTION_MS = {
  uiFast: 150,
  ui: 200,
  data: 400,
  page: 360,
  panel: 280,
} as const;

export type MotionKind = keyof typeof MOTION_MS;

/** `--motion-ease`, as the four control points of its cubic Bézier. */
export const MOTION_EASE = [0.2, 0, 0, 1] as const;
export const MOTION_ROUTE_EASE = [0.22, 0.61, 0.36, 1] as const;

export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

type MediaSource = Pick<Window, "matchMedia"> | undefined;

/** Whether the viewer asked for reduced motion; false where the browser cannot say. */
export function prefersReducedMotion(source: MediaSource = globalThis.window): boolean {
  if (source === undefined || typeof source.matchMedia !== "function") return false;
  return source.matchMedia(REDUCED_MOTION_QUERY).matches;
}

/** The duration of one kind of change in milliseconds: zero under reduced motion. */
export function motionDuration(kind: MotionKind, source: MediaSource = globalThis.window): number {
  return prefersReducedMotion(source) ? 0 : MOTION_MS[kind];
}
