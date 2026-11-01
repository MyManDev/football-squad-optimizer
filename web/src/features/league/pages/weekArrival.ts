import { useLayoutEffect, useRef, type RefObject } from "react";

import { MOTION_EASE, motionDuration } from "../../../design/motion";

/**
 * The week screen's arrival (#1136). When the member page is drawn, the decision card rises
 * into place and the pitch's plates appear one after another from the keeper forward. When
 * the decision is first drawn (at once, or once its plan has been read), its boards follow
 * the card a step apart, and the gain's bar fills from nothing to its value while the figure
 * beside it counts up from nothing to the same value in the same time (`countUp`). Each part moves once for the page; a later plan has the boards' own motion
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

/**
 * A plate appears where it stands, in opacity alone: a scale would shrink its box and the
 * marks inside it (the coach-news link's 24 px target among them) for as long as it runs.
 */
export const APPEAR: Keyframe[] = [{ opacity: 0 }, { opacity: 1 }];

/**
 * The gain's figure counts up from nothing to its value in `duration`, in the figure's own
 * sign, decimal separator and decimals. Only the text on screen moves: the figure is not a
 * live region, so a screen reader is told none of the numbers on the way. The first painted
 * frame already shows the start, as this runs in a layout effect; a figure the page redraws
 * meanwhile (a new plan, a new language) is left as the page drew it.
 */
export function countUp(element: Element, duration: number): void {
  const node = element.firstChild;
  if (!(node instanceof Text) || typeof requestAnimationFrame !== "function") return;
  const final = node.data;
  const match = /^([+−-]?)(\d+)(?:([.,])(\d+))?$/.exec(final);
  if (!match) return;
  const [, sign = "", whole = "0", separator = "", fraction = ""] = match;
  const target = Number(`${whole}.${fraction || "0"}`);
  if (!(target > 0)) return;
  const shown = (value: number) => {
    const digits = value.toFixed(fraction.length);
    return `${sign}${separator ? digits.replace(".", separator) : digits}`;
  };
  const start = performance.now();
  let written = shown(0);
  node.data = written;
  // Each frame reads the same clock the start did, not the frame's own timestamp, whose
  // origin a browser or a test environment may set apart.
  const frame = () => {
    if (node.data !== written) return;
    const progress = Math.min(1, (performance.now() - start) / duration);
    written = progress < 1 ? shown(target * (1 - (1 - progress) ** 3)) : final;
    node.data = written;
    if (progress < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

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
  const figure = card.querySelector('[data-arrival="gain"]');
  if (figure && typeof figure.animate === "function") countUp(figure, data);
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
