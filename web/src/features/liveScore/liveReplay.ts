/**
 * The GOL replay (`?replay=1` on the member page, the owner's way to see the moment on the live
 * site before a match is played): one live read's goals and assists for the member's picks,
 * one at a time, as if each had come in a read of its own. The member page's replay
 * (`useGoalReplay`) plays the week's automatic substitutions after them.
 */

import { MOTION_MS } from "../../design/motion";
import type { LiveEvent } from "./liveEvents";
import type { LiveActivity } from "./weekActivity";

/** The first step comes a moment after the cover has gone. */
export const REPLAY_START_MS = MOTION_MS.data * 3;

/** One step: a board's rise, stay and fall, or a still line's stay, then a breath. */
export const REPLAY_STEP_MS = MOTION_MS.data * 16;

/**
 * Each goal and assist of the member's picks in `activity`, one event each: the fixtures in the
 * read's order, within a fixture the picks in pick order, a player's goals before his assists.
 */
export function replayEvents(activity: LiveActivity, picks: readonly number[]): LiveEvent[] {
  const place = new Map(picks.map((elementId, index) => [elementId, index]));
  const rows = activity.appearances
    .filter((row) => place.has(row.element_id))
    .sort(
      (a, b) => a.fixture_id - b.fixture_id || place.get(a.element_id)! - place.get(b.element_id)!,
    );
  const events: LiveEvent[] = [];
  for (const row of rows) {
    for (let goal = 0; goal < row.goals; goal += 1) {
      events.push({ kind: "goal", elementId: row.element_id, count: 1 });
    }
    for (let assist = 0; assist < row.assists; assist += 1) {
      events.push({ kind: "assist", elementId: row.element_id, count: 1 });
    }
  }
  return events;
}
