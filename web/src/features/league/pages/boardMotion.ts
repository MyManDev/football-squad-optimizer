import { MOTION_EASE, motionDuration } from "../../../design/motion";

/**
 * The substitution board's one short motion (#1131): when a board first shows a transfer
 * pair, the outgoing panel steps back and returns while the incoming one arrives, both in
 * the data time of the motion tokens, and the gain appears once they have finished. Only
 * `transform` and `opacity` move. It runs once per change of the pair on a board's slot,
 * never on a re-render or a scroll, and under the reduced-motion preference it does not
 * run at all, so the board is shown in its end state at once.
 */

export const BOARD_EASE = `cubic-bezier(${MOTION_EASE.join(", ")})`;

/** The incoming player arrives from a little to the right. */
export const INCOMING: Keyframe[] = [
  { opacity: 0, transform: "translateX(12px)" },
  { opacity: 1, transform: "none" },
];

/** The outgoing player steps back and returns: he stays on the board. */
export const OUTGOING: Keyframe[] = [
  { opacity: 1, transform: "none" },
  { opacity: 0.6, transform: "translateX(-6px) scale(0.98)", offset: 0.5 },
  { opacity: 1, transform: "none" },
];

/** The gain comes up once the players have moved. */
export const GAIN: Keyframe[] = [{ opacity: 0 }, { opacity: 1 }];

export interface BoardParts {
  outgoing: HTMLElement | null;
  incoming: HTMLElement | null;
  gain: HTMLElement | null;
}

type MediaSource = Pick<Window, "matchMedia"> | undefined;

/** Starts the motion on the board's parts; returns the animations, none under reduced motion. */
export function playBoard(parts: BoardParts, source?: MediaSource): Animation[] {
  const data = motionDuration("data", source);
  const ui = motionDuration("ui", source);
  const { outgoing, incoming, gain } = parts;
  if (data === 0 || !outgoing || !incoming || !gain || typeof incoming.animate !== "function")
    return [];
  return [
    outgoing.animate(OUTGOING, { duration: data, easing: BOARD_EASE }),
    incoming.animate(INCOMING, { duration: data, easing: BOARD_EASE, fill: "backwards" }),
    gain.animate(GAIN, { duration: ui, delay: data, easing: BOARD_EASE, fill: "backwards" }),
  ];
}

// The pair each board slot last showed, for the page's life: a board that mounts again
// with the pair it showed before (a reload of the same selection) does not move again.
const shownPairs = new Map<string, string>();

/** The slot of a member's board at `index`: the member and the board's place. */
export function boardSlot(member: number, index: number): string {
  return `${member}:${index}`;
}

/**
 * Whether a board slot is showing a pair it has not shown before, and if so records it.
 * `slot` names the member and the board's place; `pair` the players out and in.
 */
export function claimPair(slot: string, pair: string): boolean {
  if (shownPairs.get(slot) === pair) return false;
  shownPairs.set(slot, pair);
  return true;
}

/** Lets a slot's pair move again, for a motion that was stopped before it finished. */
export function releasePair(slot: string, pair: string): void {
  if (shownPairs.get(slot) === pair) shownPairs.delete(slot);
}

/**
 * Empties a member's slots from `count` on, for a decision drawn with `count` boards (none
 * for a hold week): those places show no pair now, so a pair that comes back to one of
 * them later is a change of the pair and moves.
 */
export function releaseSlotsFrom(member: number, count: number): void {
  for (const slot of shownPairs.keys()) {
    const [owner, place] = slot.split(":");
    if (owner === String(member) && Number(place) >= count) shownPairs.delete(slot);
  }
}

/** For tests: every slot starts unseen. */
export function forgetPairs(): void {
  shownPairs.clear();
}
