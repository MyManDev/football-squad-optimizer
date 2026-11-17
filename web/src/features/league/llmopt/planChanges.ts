import { clubCountKey, type PlanWeekNumber } from "../advice/decisionPreferences";
import type { Constraint, PlanDraft } from "./intent";

export type RuleMark = "added" | "changed";

export type DraftItem =
  | { group: "hard" | "soft" | "comparison"; rule: Constraint }
  | { group: "revision"; keepWeek: PlanWeekNumber }
  | { group: "revision"; bank: NonNullable<PlanDraft["min_bank"]> }
  | { group: "scenario"; scenario: NonNullable<PlanDraft["scenario"]> };

/** What a model answer did to the draft: marks on the rules it now holds, and the ones it dropped. */
export interface DraftChanges {
  marks: ReadonlyMap<string, RuleMark>;
  removed: readonly DraftItem[];
}

/**
 * The same rule across two drafts in one group, whatever its amount: a player rule by player and
 * week, a club rule by club, scope and week, the penalty limit and the bank floor as one each.
 * A rule moved between groups reads as removed from one and added to the other.
 */
export function ruleIdentity(group: "hard" | "soft" | "comparison", rule: Constraint): string {
  const week = rule.week === undefined ? "" : `:${rule.week}`;
  if (rule.kind === "club_count") return `${group}:${rule.kind}:${clubCountKey(rule)}${week}`;
  if (rule.kind === "hit_budget") return `${group}:${rule.kind}`;
  return "player_id" in rule
    ? `${group}:${rule.kind}:${rule.player_id}${week}`
    : `${group}:${rule.kind}${week}`;
}

export const KEEP_WEEK = (week: PlanWeekNumber) => `revision:keep:${week}`;
export const BANK_FLOOR = "revision:bank";
export const SCENARIO = "scenario";

function itemIdentity(item: DraftItem): string {
  if ("rule" in item) return ruleIdentity(item.group, item.rule);
  if ("keepWeek" in item) return KEEP_WEEK(item.keepWeek);
  if ("bank" in item) return BANK_FLOOR;
  return SCENARIO;
}

function draftItems(draft: PlanDraft): DraftItem[] {
  return [
    ...draft.hard.map((rule) => ({ group: "hard" as const, rule })),
    ...draft.soft.map((rule) => ({ group: "soft" as const, rule })),
    ...(draft.comparison ? [{ group: "comparison" as const, rule: draft.comparison }] : []),
    ...(draft.keep_weeks ?? []).map((keepWeek) => ({ group: "revision" as const, keepWeek })),
    ...(draft.min_bank ? [{ group: "revision" as const, bank: draft.min_bank }] : []),
    ...(draft.scenario ? [{ group: "scenario" as const, scenario: draft.scenario }] : []),
  ];
}

/** A value that does not depend on the order its fields were written in. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.entries(value)
      .filter(([, field]) => field !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, field]) => `${JSON.stringify(key)}:${canonical(field)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}

/** The rules a model answer added, changed or removed; null when it changed none. */
export function draftChanges(before: PlanDraft, after: PlanDraft): DraftChanges | null {
  const earlier = new Map(draftItems(before).map((item) => [itemIdentity(item), item]));
  const marks = new Map<string, RuleMark>();
  const kept = new Set<string>();
  for (const item of draftItems(after)) {
    const identity = itemIdentity(item);
    const previous = earlier.get(identity);
    kept.add(identity);
    if (!previous) marks.set(identity, "added");
    else if (canonical(previous) !== canonical(item)) marks.set(identity, "changed");
  }
  const removed = [...earlier].flatMap(([identity, item]) => (kept.has(identity) ? [] : [item]));
  return marks.size || removed.length ? { marks, removed } : null;
}
