import { useLayoutEffect, useRef, type RefObject } from "react";

import { MOTION_EASE, motionDuration } from "../../../design/motion";

/**
 * The week screen's arrival (#1136). When the member page is drawn, the decision card rises
 * into place and the pitch's plates appear one after another from the keeper forward. When
 * the decision is first drawn (at once, or once its plan has been read), its boards follow
 * the card a step apart, and the gain's bar fills from nothing to its value while the figure
 * comes up beside it, its final value from the first frame: it never counts, so no number on
 * the way is read. Each part moves once for the page; a later plan has the boards' own motion
 * and the pitch's movement, and the list and back, a new language or a resize move nothing.
 * Only opacity, transform and the bar's clip move, in the motion tokens' times; under the
 * reduced-motion preference nothing runs.
 *
 * Nothing is cancelled when a part leaves: a script animation runs out on a detached element,
 * while a cancelled one rejects the `finished` a caller may wait on. A plate the newly read
 * plan takes off the pitch ends its motion unseen.
 */

const EASE = `cubic-bezier(${MOTION_EASE.join(", ")})`;

/** The card and each board rise a little into place. */
export const RISE: Keyframe[] = [
  { opacity: 0, transform: "translateY(8px)" },
  { opacity: 1, transform: "none" },
];

/** The bar fills from its start to its value: uncovered, not stretched, so its labels hold. */
export const FILL: Keyframe[] = [{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }];

/** A plate appears where it stands: its centre never moves, so the lines hold their places. */
export const APPEAR: Keyframe[] = [
  { opacity: 0, transform: "scale(0.94)" },
  { opacity: 1, transform: "none" },
];

/** Board steps after the card, at most: a Wildcard's fifteen boards do not queue for a second. */
const BOARD_STEPS = 6;

type MediaSource = Pick<Window, "matchMedia"> | undefined;

function play(element: Element, keyframes: Keyframe[], duration: number, delay = 0) {
  if (typeof element.animate !== "function") return [];
  // Backwards, so a part that waits its turn is not seen at rest before it moves.
  return [element.animate(keyframes, { duration, delay, easing: EASE, fill: "backwards" })];
}

/** The page's part: the decision card, and the plates in the pitch's order, keeper first. */
export function playPage(root: ParentNode, source?: MediaSource): Animation[] {
  const ui = motionDuration("ui", source);
  if (ui === 0) return [];
  const data = motionDuration("data", source);
  const step = motionDuration("uiFast", source) / 6;
  const card = root.querySelector('[data-mark="decision"]');
  const plates = [...root.querySelectorAll('[data-mark="pitch"] [data-plate]')];
  return [
    ...(card ? play(card, RISE, ui) : []),
    ...plates.flatMap((plate, index) => play(plate, APPEAR, data, index * step)),
  ];
}

/** The decision's part: each board a step after the one before, the gain and its bar together. */
export function playDecision(root: ParentNode, source?: MediaSource): Animation[] {
  const ui = motionDuration("ui", source);
  const card = root.querySelector('[data-mark="decision"]');
  if (ui === 0 || !card) return [];
  const data = motionDuration("data", source);
  const step = motionDuration("uiFast", source) / 3;
  const rows = [...card.querySelectorAll('[data-arrival="row"]')];
  const gain = [...card.querySelectorAll('[data-arrival="gain"], [data-arrival="bar"]')];
  return [
    ...rows.flatMap((row, index) => play(row, RISE, ui, Math.min(index + 1, BOARD_STEPS) * step)),
    ...gain.flatMap((part) =>
      play(part, part.getAttribute("data-arrival") === "bar" ? FILL : RISE, data),
    ),
  ];
}

/**
 * Runs the arrival under `root`: the page's part on the first draw, the decision's part on
 * the first draw that shows a decision. A layout effect, so the first frame painted is the
 * first frame of the motion and never the page at rest a moment before it.
 */
export function useWeekArrival(root: RefObject<HTMLElement | null>, decided: boolean): void {
  const moved = useRef({ page: false, decision: false });
  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    if (!moved.current.page) {
      moved.current.page = true;
      playPage(element);
    }
    if (decided && !moved.current.decision) {
      moved.current.decision = true;
      playDecision(element);
    }
  }, [root, decided]);
}
