/**
 * The GOL moment's words and timeline (GoalMoment.tsx): the owner's shouts, and every step in
 * `--motion-*` units (motion.ts).
 */

import { MOTION_MS } from "../../design/motion";

/** The owner's word of 2026-11-11 for a goal's board, the same in both languages. */
export const GOAL_SHOUT = "GOOOOOOOOLLLLLL";

/**
 * The owner's word for an assist's board ("ASISSSSSSTTTTT", 2026-11-11), in Turkish capitals
 * with the dotted İ; English stretches its own word the same way.
 */
export const ASSIST_SHOUT: Readonly<Record<"tr" | "en", string>> = {
  tr: "ASİSSSSSSTTTTT",
  en: "ASSISSSSSSTTTTT",
};

/** The timeline, in `--motion-*` units (motion.ts). */
export const MOMENT_TIMING = {
  /** The board rises and goes down. */
  rise: MOTION_MS.data,
  fall: MOTION_MS.panel,
  /** How long a goal's board stays up; an assist's a step less. */
  holdGoal: MOTION_MS.data * 6,
  holdAssist: MOTION_MS.data * 5,
  /** Each LED letter lights a third of a fast UI step after the one before. */
  letter: MOTION_MS.uiFast / 3,
  /** The points' run into the live score. */
  run: MOTION_MS.data * 1.5,
  /** A small line stays this long; the still line under reduced motion longer. */
  line: MOTION_MS.data * 4,
  still: MOTION_MS.data * 15,
} as const;
