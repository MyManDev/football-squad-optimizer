/**
 * The Top 100 influence: a member's own weight on last week's Top 100 starting elevens.
 *
 * The producer solves the one-week pure-points plan once per weight and publishes every
 * number in it on the base model, so a weight is a preference with a price and never a
 * higher score. Zero is the published plan. The setting lives in the URL (`top100`), like
 * every other control on the member page, and is honoured only where the index names a
 * file for it.
 */

export const TOP100_WEIGHTS = [0, 5, 10, 20, 30, 40, 50] as const;
export type Top100Weight = (typeof TOP100_WEIGHTS)[number];

/** The URL parameter carrying the weight; absent means the published plan. */
export const TOP100_PARAMETER = "top100";

export function isTop100Weight(value: unknown): value is Top100Weight {
  return TOP100_WEIGHTS.some((weight) => weight === value);
}

/**
 * The weight the URL asks for. Absent or "0" is the published plan. A value the menu does
 * not offer is reported as such (`offered: false`) rather than read as zero without a word.
 */
export function parseTop100(params: URLSearchParams): {
  weight: Top100Weight;
  offered: boolean;
} {
  const raw = params.get(TOP100_PARAMETER);
  if (raw === null) return { weight: 0, offered: true };
  const weight = TOP100_WEIGHTS.find((candidate) => String(candidate) === raw);
  return weight === undefined ? { weight: 0, offered: false } : { weight, offered: true };
}

/** The one path a weighted document may be read from, with or without the manager's word. */
export function top100Path(entryId: number, weight: number, word: boolean): string {
  return `advice/${entryId}/saf-puan/1/top100-${weight}${word ? "-hoca-sozu" : ""}.json`;
}

/** Which plan a setting is asked for: the strategy, its window and, for a rival strategy, the rival. */
export interface Top100Target {
  strategy: string;
  window: number;
  rivalEntryId: number | null;
}

/**
 * The one path a setting's document may be read from, for any plan. The one-week
 * pure-points plan keeps its own (the only one the manager's word combines with).
 */
export function top100TargetPath(
  entryId: number,
  target: Top100Target,
  weight: number,
  word: boolean,
): string | null {
  if (target.strategy === "saf-puan" && target.window === 1) {
    return top100Path(entryId, weight, word);
  }
  if (word) return null;
  const rival = target.rivalEntryId === null ? "" : `/vs-${target.rivalEntryId}`;
  return `advice/${entryId}/${target.strategy}/${target.window}${rival}/top100-${weight}.json`;
}
