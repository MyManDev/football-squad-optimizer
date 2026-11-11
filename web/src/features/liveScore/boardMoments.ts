/**
 * Everything the GOL board raises: a goal, an assist or a card (`liveMoments`), and an automatic
 * substitution the official scorer makes (the owner's word of 2026-11-11, "oyuncu
 * değişikliklerini de göster"). Only what brings the member points is shown: a pick the scorer
 * does not count (a reserve not brought on, without the bench boost) raises nothing.
 */

import type { LiveMoment } from "./liveMoments";

/** One automatic substitution: the starter who did not play out, the reserve who counts in. */
export interface SubstitutionMoment {
  key: string;
  kind: "substitution";
  size: "big";
  out: string;
  in: string;
}

export type BoardMoment = LiveMoment | SubstitutionMoment;

/** Whether the board shows a moment: a substitution, or an event of a pick the scorer counts. */
export function shownOnBoard(moment: BoardMoment): boolean {
  return moment.kind === "substitution" || moment.multiplier > 0;
}

/**
 * The automatic substitutions a newer read adds: pairs (out, in) the scorer did not name in the
 * reads before. With no reads before, the pairs are only a starting point.
 */
export function newSubstitutions(
  seen: ReadonlySet<string> | null,
  pairs: readonly (readonly [number, number])[],
): { seen: Set<string>; fresh: [number, number][] } {
  const next = new Set(seen ?? []);
  const fresh: [number, number][] = [];
  for (const [out, incoming] of pairs) {
    const key = `${out}:${incoming}`;
    if (seen !== null && !seen.has(key)) fresh.push([out, incoming]);
    next.add(key);
  }
  return { seen: next, fresh };
}
