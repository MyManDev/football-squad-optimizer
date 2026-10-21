import type { EntryView, HumanEntryView } from "../types";

/** Two standings neighbours, the published default, and one explicitly selected member. */
export function boundedRivalIds(
  members: readonly EntryView[],
  entryId: number,
  defaultRival: number | null,
  requestedRival: string | null,
): number[] {
  const humans = members
    .filter((member): member is HumanEntryView => member.member_kind === "human")
    .toSorted((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.entry_id - b.entry_id);
  const own = humans.findIndex((member) => member.entry_id === entryId);
  const named =
    requestedRival !== null && /^\d+$/.test(requestedRival) ? Number(requestedRival) : null;
  const candidates = [
    ...(own >= 0 ? [humans[own - 1]?.entry_id, humans[own + 1]?.entry_id] : []),
    defaultRival,
    named,
  ];
  return [...new Set(candidates)].filter(
    (id): id is number =>
      typeof id === "number" &&
      Number.isSafeInteger(id) &&
      id > 0 &&
      id !== entryId &&
      humans.some((member) => member.entry_id === id),
  );
}
