/**
 * What changed in the member's fifteen between two live reads of the same week: the goals,
 * assists and cards a newer read adds. The GOL moment plays from these.
 *
 * Counts are high-water marks, as `advanceActivity` keeps them: the first read of a week is
 * only a starting point, a read that is not newer than the last one adds nothing, and a count
 * that falls (a correction, or an older copy of the document) is kept at its highest, so the
 * same goal never plays twice. A read without event detail (`activity` null) adds no goal or
 * assist and keeps the marks it had, so detail that returns later does not replay old goals;
 * and while no read of the week has had detail yet, the first one that has it is only a
 * starting point for goals and assists, so a week first read without detail never replays.
 */

import type { LiveActivity } from "./weekActivity";
import type { WeekElement } from "./weekLive";

export type LiveEventKind = "goal" | "assist" | "card";

/** One kind of event for one pick in one read: `count` goals, assists or a card. */
export interface LiveEvent {
  kind: LiveEventKind;
  elementId: number;
  count: number;
}

export interface LiveMarks {
  /** The member and week the marks belong to; another identity starts afresh. */
  identity: string;
  /** The source time of the newest read counted, in milliseconds. */
  time: number;
  /** The highest goals and assists seen, keyed `element:fixture:kind`. */
  counts: ReadonlyMap<string, number>;
  /** Whether any read counted so far had event detail, so `counts` is a starting point. */
  detailed: boolean;
  /** The picks a card has been shown to. */
  cards: ReadonlySet<number>;
}

/** One live read as the marks need it. */
export interface LiveRead {
  identity: string;
  sourceTime: string;
  elements: readonly Pick<WeekElement, "element_id" | "card_shown">[];
  activity: LiveActivity | null;
}

const KINDS = [
  ["goals", "goal"],
  ["assists", "assist"],
] as const;

/**
 * The marks after `read`, and the events it adds for `picks`. The first read of an identity,
 * and a read no newer than the last, add none.
 */
export function advanceLiveMarks(
  previous: LiveMarks | null,
  read: LiveRead,
  picks: readonly number[],
): { marks: LiveMarks; events: LiveEvent[] } {
  const time = Date.parse(read.sourceTime);
  const same = previous !== null && previous.identity === read.identity;
  if (!Number.isFinite(time)) return { marks: previous ?? empty(read.identity), events: [] };
  if (same && time <= previous.time) return { marks: previous, events: [] };
  const counts = new Map(same ? previous.counts : []);
  const cards = new Set(same ? previous.cards : []);
  // Goals and assists count against marks that came from a read with detail.
  const counting = same && previous.detailed;
  const found = new Map<string, LiveEvent>();
  const add = (kind: LiveEventKind, elementId: number, count: number) => {
    const key = `${kind}:${elementId}`;
    const event = found.get(key);
    if (event) event.count += count;
    else found.set(key, { kind, elementId, count });
  };
  const chosen = new Set(picks);
  for (const appearance of read.activity?.appearances ?? []) {
    if (!chosen.has(appearance.element_id)) continue;
    for (const [field, kind] of KINDS) {
      const key = `${appearance.element_id}:${appearance.fixture_id}:${kind}`;
      const seen = counts.get(key) ?? 0;
      const value = appearance[field];
      // A count the read leaves out keeps the mark as it was, never NaN.
      if (!Number.isFinite(value)) continue;
      if (counting && value > seen) add(kind, appearance.element_id, value - seen);
      counts.set(key, Math.max(seen, value));
    }
  }
  for (const element of read.elements) {
    if (!chosen.has(element.element_id) || !element.card_shown) continue;
    if (same && !cards.has(element.element_id)) add("card", element.element_id, 1);
    cards.add(element.element_id);
  }
  return {
    marks: {
      identity: read.identity,
      time,
      counts,
      cards,
      detailed: (same && previous.detailed) || read.activity !== null,
    },
    events: picks.flatMap((elementId) =>
      (["goal", "assist", "card"] as const)
        .map((kind) => found.get(`${kind}:${elementId}`))
        .filter((event): event is LiveEvent => event !== undefined),
    ),
  };
}

function empty(identity: string): LiveMarks {
  return {
    identity,
    time: Number.NEGATIVE_INFINITY,
    counts: new Map(),
    cards: new Set(),
    detailed: false,
  };
}
