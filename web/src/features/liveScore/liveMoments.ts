/**
 * The GOL moments one read brings: each event of `liveEvents` with the player it belongs to
 * and the points it brings the member, ordered and sized for the board (#1008 follow-up,
 * the owner's Plan 1 of 2026-11-11).
 *
 * - A goal or an assist that counts for the member is a big moment (the owner's word of
 *   2026-11-11 put the assist beside the goal): goals first, then assists, the biggest points
 *   first within each. At most three big moments play for one read; any further one plays small.
 * - A card, and anything from a pick who does not count (a reserve not brought on, without the
 *   bench boost), is small.
 *
 * The points are the season's own value of the event for the player's position, times the
 * armband: 2 for the captain the official scorer names, 3 under the triple captain, 0 for a
 * pick it does not count. A card's points are not known from the live document (it does not
 * say yellow or red), so a card carries none; nor does an event in a season whose values are
 * not listed here.
 */

import type { LiveEvent, LiveEventKind } from "./liveEvents";
import type { Position } from "./weekLive";

export type LiveMomentSize = "big" | "small";

export interface LiveMoment {
  /** Unique within the page session: the read's number, the kind and the player. */
  key: string;
  kind: LiveEventKind;
  size: LiveMomentSize;
  elementId: number;
  name: string;
  team: string;
  position: Position;
  count: number;
  /** The armband on this read: 0 when the pick does not count. */
  multiplier: 0 | 1 | 2 | 3;
  /** The event's points before the armband, or null where they are not known. */
  base: number | null;
  /** The points the member receives, or null where they are not known. */
  points: number | null;
}

/**
 * Each season's points for a goal and an assist, as FPL's `game_config` states them
 * (`scoring.goals_scored`, `scoring.assists`); 2026-27 was read from the bootstrap on
 * 2026-08-16 and again on 2026-09-12.
 */
export const SEASON_EVENT_POINTS: Readonly<
  Record<string, { goal: Readonly<Record<Position, number>>; assist: number }>
> = {
  "2026-27": { goal: { GK: 10, DEF: 6, MID: 5, FWD: 4 }, assist: 3 },
};

/** At most this many big moments play for one read. */
export const MAX_BIG_MOMENTS = 3;

/** What the page knows of the read: the season, the scorer's verdict and each pick. */
export interface MomentContext {
  read: number;
  season: string;
  /** The picks the official scorer counts this read. */
  counted: readonly number[];
  /** The armband's holder after the scorer's rules, or null. */
  captain: number | null;
  tripleCaptain: boolean;
  players: ReadonlyMap<number, { name: string; team: string; position: Position }>;
}

const RANK: Record<LiveMomentSize, number> = { big: 0, small: 1 };
const KIND: Record<LiveEventKind, number> = { goal: 0, assist: 1, card: 2 };

/** Big before small, goals before assists before cards, then the most points first. */
const order = (a: LiveMoment, b: LiveMoment) =>
  RANK[a.size] - RANK[b.size] || KIND[a.kind] - KIND[b.kind] || (b.points ?? 0) - (a.points ?? 0);

export function liveMoments(events: readonly LiveEvent[], context: MomentContext): LiveMoment[] {
  const values = SEASON_EVENT_POINTS[context.season];
  const counted = new Set(context.counted);
  const moments: LiveMoment[] = [];
  for (const event of events) {
    const player = context.players.get(event.elementId);
    if (player === undefined || event.count < 1) continue;
    const multiplier: LiveMoment["multiplier"] = !counted.has(event.elementId)
      ? 0
      : event.elementId === context.captain
        ? context.tripleCaptain
          ? 3
          : 2
        : 1;
    const each =
      values === undefined || event.kind === "card"
        ? null
        : event.kind === "goal"
          ? values.goal[player.position]
          : values.assist;
    const base = each === null ? null : each * event.count;
    const size: LiveMomentSize = multiplier === 0 || event.kind === "card" ? "small" : "big";
    moments.push({
      key: `${context.read}:${event.kind}:${event.elementId}`,
      kind: event.kind,
      size,
      elementId: event.elementId,
      name: player.name,
      team: player.team,
      position: player.position,
      count: event.count,
      multiplier,
      base,
      points: base === null ? null : base * multiplier,
    });
  }
  moments.sort(order);
  let big = 0;
  for (const moment of moments) {
    if (moment.size === "big" && ++big > MAX_BIG_MOMENTS) moment.size = "small";
  }
  return moments.sort(order);
}
