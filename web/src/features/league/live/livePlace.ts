/**
 * Where the visitor reads on LIVE, so a change above it leaves it where it was on the screen
 * (LiveView's LiveFlow scrolls by how far it moved). Pure: it reads only the tops it is given.
 */

/** A row, a heading or Farklar, by a key that outlives a change of group, and its top. */
export interface Place {
  part: string;
  top: number;
}

/**
 * What the visitor may be reading, likeliest first, where they read past the groups' top (none
 * where the groups' top is in sight): the parts wholly below the bar from the top down, then
 * those the bar's line falls in or that stand above it from the bar up, so reading inside an
 * open Farklar on a screen without a bar still has one. A part the read takes elsewhere (`moves`)
 * is none of them.
 */
export function readingAnchors(
  tops: readonly (readonly [string, number])[],
  bar: number,
  groupsTop: number,
  moves: (part: string) => boolean,
): Place[] {
  if (groupsTop > bar) return [];
  const kept = tops.filter(([part]) => !moves(part)).map(([part, top]) => ({ part, top }));
  return [
    ...kept.filter(({ top }) => top >= bar).sort((a, b) => a.top - b.top),
    ...kept.filter(({ top }) => top < bar).sort((a, b) => b.top - a.top),
  ];
}

/**
 * How far the page scrolls to keep the part read where it was: the first anchor still there
 * after the change (a heading whose group the read emptied is not), by how far it moved; 0 where
 * none moved by a pixel or more.
 */
export function keepBy(anchors: readonly Place[], now: ReadonlyMap<string, number>): number {
  const anchor = anchors.find(({ part }) => now.has(part));
  if (anchor === undefined) return 0;
  const moved = now.get(anchor.part)! - anchor.top;
  return Math.abs(moved) < 1 ? 0 : moved;
}
