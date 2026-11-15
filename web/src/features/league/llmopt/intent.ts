import { discardBody, withRequestDeadline } from "../../../data/request";
import type { Language } from "../../../i18n/messages";
import {
  checkedBankFloor,
  checkedPreferences,
  clubCountKey,
  isHitBudget,
  isPlanWeek,
  preferencesKey,
  type BankFloor,
  type ClubCount,
  type DecisionPreferences,
  type FrozenPlanWeek,
  type PlanWeekNumber,
} from "../advice/decisionPreferences";

const playerKinds = ["keep_player", "include_player", "avoid_player"] as const;
const ruleKinds = ["hold_transfers", "no_hits", "save_chips", "wildcard"] as const;

export const CONSTRAINT_KINDS = [
  ...ruleKinds,
  ...playerKinds,
  "buy_player",
  "club_count",
  "hit_budget",
] as const;
export const MAX_CONSTRAINTS = 16;
export const MAX_MESSAGE_LENGTH = 800;
export const MAX_QUESTION_LENGTH = 300;

type PlayerKind = (typeof playerKinds)[number] | "buy_player";
type PlanWindow = 1 | 3;
export type Constraint = (
  | ({ week?: PlanWeekNumber } & (
      | { kind: (typeof playerKinds)[number]; player_id: number }
      | { kind: (typeof ruleKinds)[number] }
      | ({ kind: "club_count" } & ClubCount)
    ))
  | { kind: "buy_player"; player_id: number; week: PlanWeekNumber }
  | { kind: "hit_budget"; points: number; week?: never }
) & { max_cost_tenths?: number };
type Comparison = Constraint & { both?: boolean };

export interface PlanDraft {
  hard: Constraint[];
  soft: Constraint[];
  comparison?: Comparison;
  window?: PlanWindow;
  keep_weeks?: PlanWeekNumber[];
  min_bank?: BankFloor;
}

interface PreparedPlan {
  chip: "wildcard" | null;
  preferences: DecisionPreferences;
}

export interface CatalogPlayer {
  id: number;
  name: string;
  team: string;
  held?: boolean;
}

export interface Clarification {
  message: string;
  question: string;
}

export const EMPTY_DRAFT: PlanDraft = { hard: [], soft: [] };

export function isPlayerKind(kind: Constraint["kind"]): kind is PlayerKind {
  return (
    kind === "keep_player" ||
    kind === "include_player" ||
    kind === "avoid_player" ||
    kind === "buy_player"
  );
}

export function needsThreeWeeks(draft: PlanDraft) {
  const rules = [...draft.hard, ...draft.soft, ...(draft.comparison ? [draft.comparison] : [])];
  return [...rules.map(({ week }) => week), ...(draft.keep_weeks ?? []), draft.min_bank?.week].some(
    (week) => week === 2 || week === 3,
  );
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isPreferenceCost(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 1000;
}

function parseConstraint(
  value: unknown,
  players: ReadonlySet<number>,
  clubs: ReadonlySet<string>,
  strength: "hard" | "soft" | "comparison" = "hard",
) {
  if (
    !record(value) ||
    !CONSTRAINT_KINDS.some((kind) => kind === value.kind) ||
    Object.keys(value).some(
      (key) =>
        !["kind", "player_id", "club", "count", "scope", "week", "points"].includes(key) &&
        !(strength === "comparison" && key === "both") &&
        !(strength === "soft" && key === "max_cost_tenths"),
    )
  )
    throw new Error("Invalid constraint");
  const kind = value.kind as Constraint["kind"];
  const id = value.player_id;
  const { club, count, scope, week, points, max_cost_tenths: maxCost } = value;
  if (maxCost !== undefined && !isPreferenceCost(maxCost))
    throw new Error("Invalid preference cost limit");
  const price = maxCost === undefined ? {} : { max_cost_tenths: maxCost };
  if (week !== undefined && !isPlanWeek(week)) throw new Error("Invalid rule week");
  const timing = week === undefined ? {} : { week };
  if (kind === "hit_budget") {
    if (
      id !== undefined ||
      club !== undefined ||
      count !== undefined ||
      scope !== undefined ||
      week !== undefined ||
      !isHitBudget(points)
    )
      throw new Error("Invalid hit budget");
    return { kind, points, ...price } satisfies Constraint;
  }
  if (points !== undefined) throw new Error("Unexpected hit budget");
  if (kind === "club_count") {
    if (
      id !== undefined ||
      typeof club !== "string" ||
      !clubs.has(club) ||
      (count !== 1 && count !== 2 && count !== 3) ||
      (scope !== undefined && scope !== "squad" && scope !== "transfers_in")
    )
      throw new Error("Invalid club count");
    return {
      kind,
      club,
      count,
      ...(scope === "transfers_in" ? { scope } : {}),
      ...timing,
      ...price,
    } satisfies Constraint;
  }
  if (club !== undefined || count !== undefined || scope !== undefined)
    throw new Error("Unexpected club count");
  if (isPlayerKind(kind)) {
    if (typeof id !== "number" || !players.has(id)) throw new Error("Unknown player");
    if (kind === "buy_player") {
      if (week === undefined) throw new Error("A transfer needs a week");
      return { kind, player_id: id, week, ...price } satisfies Constraint;
    }
    return { kind, player_id: id, ...timing, ...price } satisfies Constraint;
  }
  if (id !== undefined) throw new Error("Unexpected player");
  return { kind, ...timing, ...price } satisfies Constraint;
}

export function checkedDraft(value: unknown, players: readonly CatalogPlayer[]): PlanDraft {
  if (
    !record(value) ||
    !Array.isArray(value.hard) ||
    !Array.isArray(value.soft) ||
    (value.window !== undefined && value.window !== 1 && value.window !== 3) ||
    value.hard.length + value.soft.length > MAX_CONSTRAINTS
  )
    throw new Error("Invalid draft");
  const playerIds = new Set(players.map(({ id }) => id));
  const clubs = new Set(players.map(({ team }) => team).filter(Boolean));
  const draft: PlanDraft = {
    hard: value.hard.map((item) => parseConstraint(item, playerIds, clubs)),
    soft: value.soft.map((item) => parseConstraint(item, playerIds, clubs, "soft")),
    ...(value.window !== undefined ? { window: value.window } : {}),
  };
  if (value.keep_weeks !== undefined) {
    if (
      !Array.isArray(value.keep_weeks) ||
      !value.keep_weeks.every(isPlanWeek) ||
      new Set(value.keep_weeks).size !== value.keep_weeks.length
    )
      throw new Error("Invalid reference weeks");
    if (value.keep_weeks.length) draft.keep_weeks = [...value.keep_weeks].sort((a, b) => a - b);
  }
  if (value.min_bank !== undefined) draft.min_bank = checkedBankFloor(value.min_bank);
  const keys = [...draft.hard, ...draft.soft].map(constraintKey);
  if (new Set(keys).size !== keys.length) throw new Error("Repeated constraint");
  if (value.comparison != null) {
    const item = parseConstraint(value.comparison, playerIds, clubs, "comparison");
    const both = (value.comparison as Record<string, unknown>).both;
    if (both != null && (typeof both !== "boolean" || (both && item.kind !== "include_player")))
      throw new Error("Invalid comparison");
    draft.comparison = both === true ? { ...item, both: true } : item;
  }
  if (needsThreeWeeks(draft)) {
    if (draft.window === 1) throw new Error("Rule outside the plan window");
    draft.window = 3;
  }
  return draft;
}

export function constraintKey(rule: Constraint): string {
  const scope = rule.week === undefined ? "" : `:week:${rule.week}`;
  if (rule.kind === "club_count") return `${rule.kind}:${clubCountKey(rule)}:${rule.count}${scope}`;
  if (rule.kind === "hit_budget") return `${rule.kind}:${rule.points}`;
  return "player_id" in rule ? `${rule.kind}:${rule.player_id}${scope}` : `${rule.kind}${scope}`;
}

function playerIds(rules: readonly Constraint[], kind: PlayerKind) {
  return [...new Set(rules.flatMap((rule) => (rule.kind === kind ? [rule.player_id] : [])))];
}

function ruleFields(rules: readonly Constraint[]) {
  const buy = playerIds(rules, "buy_player");
  return {
    keep_players: playerIds(rules, "keep_player"),
    include_players: playerIds(rules, "include_player"),
    avoid_players: playerIds(rules, "avoid_player"),
    no_hits: rules.some(({ kind }) => kind === "no_hits"),
    hold_transfers: rules.some(({ kind }) => kind === "hold_transfers"),
    save_chips: rules.some(({ kind }) => kind === "save_chips"),
    club_counts: clubCounts(rules),
    ...(buy.length ? { buy_players: buy } : {}),
  };
}

function clubCounts(rules: readonly Constraint[]): ClubCount[] {
  const counts = new Map<string, ClubCount>();
  for (const rule of rules) {
    if (rule.kind !== "club_count") continue;
    const { club, count, scope } = rule;
    counts.set(constraintKey(rule), { club, count, ...(scope ? { scope } : {}) });
  }
  return [...counts.values()];
}

function branchSelection(
  rules: readonly Constraint[],
  held: ReadonlySet<number>,
  window: PlanWindow,
  frozenWeeks: readonly FrozenPlanWeek[],
  minBank: BankFloor | undefined,
): PreparedPlan | null {
  if (rules.some(({ week }) => week !== undefined && week > window)) return null;
  if (playerIds(rules, "keep_player").some((id) => !held.has(id))) return null;
  const forcedWeeks = new Set(
    rules.flatMap(({ kind, week }) => (kind === "wildcard" ? [week ?? 1] : [])),
  );
  for (const frozen of frozenWeeks) {
    if (frozen.chip === "wildcard") forcedWeeks.add(frozen.week);
    else if (frozen.chip !== null) return null;
  }
  if (forcedWeeks.size > 1) return null;
  const wildcardWeek = [...forcedWeeks][0];
  if (frozenWeeks.some(({ week, chip }) => week === wildcardWeek && chip === null)) return null;
  const global = ruleFields(rules.filter(({ week }) => week === undefined));
  const weekRules = ([1, 2, 3] as const).flatMap((week) => {
    const scoped = rules.filter((rule) => rule.week === week && rule.kind !== "wildcard");
    return scoped.length ? [{ week, rules: ruleFields(scoped) }] : [];
  });
  const firstWeek = weekRules.find(({ week }) => week === 1)?.rules;
  if (firstWeek?.buy_players?.some((id) => held.has(id))) return null;
  if (global.hold_transfers || firstWeek?.hold_transfers) {
    const fixedWeeks = global.hold_transfers
      ? weekRules
      : weekRules.filter(({ week }) => week === 1);
    const fixed = [global, ...fixedWeeks.map(({ rules }) => rules)];
    if (
      fixed.some(
        (row) =>
          row.include_players.some((id) => !held.has(id)) ||
          row.avoid_players.some((id) => held.has(id)),
      )
    )
      return null;
  }
  if (
    wildcardWeek === 1 &&
    (global.hold_transfers ||
      global.save_chips ||
      firstWeek?.hold_transfers ||
      firstWeek?.save_chips)
  )
    return null;
  const caps = rules.flatMap((rule) => (rule.kind === "hit_budget" ? [rule.points] : []));
  try {
    return {
      chip: wildcardWeek === 1 ? "wildcard" : null,
      preferences: checkedPreferences({
        ...global,
        save_chips: wildcardWeek === undefined || global.save_chips,
        ...(weekRules.length ? { week_rules: weekRules } : {}),
        ...(caps.length ? { max_hit_points: Math.min(...caps) } : {}),
        ...(wildcardWeek === 2 || wildcardWeek === 3 ? { wildcard_week: wildcardWeek } : {}),
        ...(frozenWeeks.length ? { frozen_weeks: frozenWeeks } : {}),
        ...(minBank ? { min_bank: minBank } : {}),
      }),
    };
  } catch {
    return null;
  }
}

export function preparePlans(
  draft: PlanDraft,
  held: ReadonlySet<number>,
  frozenWeeks: readonly FrozenPlanWeek[] = [],
) {
  const window = draft.window ?? (needsThreeWeeks(draft) ? 3 : 1);
  const keepWeeks = draft.keep_weeks ?? [];
  const resolved =
    keepWeeks.length === frozenWeeks.length &&
    keepWeeks.every((week) => week <= window && frozenWeeks.some((row) => row.week === week)) &&
    (draft.min_bank?.week ?? 1) <= window;
  const select = (rules: readonly Constraint[]) =>
    resolved ? branchSelection(rules, held, window, frozenWeeks, draft.min_bank) : null;
  const both = draft.comparison?.kind === "include_player" && draft.comparison.both;
  const baseRules: Constraint[] =
    both && draft.comparison?.kind === "include_player"
      ? [
          ...draft.hard,
          {
            kind: "avoid_player",
            player_id: draft.comparison.player_id,
            week: draft.comparison.week,
          },
        ]
      : draft.hard;
  const alternativeRules = [...draft.hard, ...(draft.comparison ? [draft.comparison] : draft.soft)];
  const hard = select(draft.hard);
  const base = both ? select(baseRules) : hard;
  const alternative = select(alternativeRules);
  return {
    window,
    base,
    alternative:
      alternative &&
      (!base ||
        base.chip !== alternative.chip ||
        preferencesKey(base.preferences) !== preferencesKey(alternative.preferences))
        ? alternative
        : null,
    hardConflict: hard === null,
    baseConflict: base === null,
    alternativeConflict: alternative === null,
  };
}

export async function readIntentCatalog(origin: string, season: string, signal: AbortSignal) {
  return withRequestDeadline(
    async (signal) => {
      const response = await fetch(`${origin}/api/v1/contributions/players`, { signal });
      if (!response.ok) {
        await discardBody(response);
        throw new Error("Roster unavailable");
      }
      const value: unknown = await response.json();
      if (
        !record(value) ||
        value.season !== season ||
        !Array.isArray(value.players) ||
        !value.players.length ||
        value.players.length > 1000
      )
        throw new Error("Invalid roster");
      const seen = new Set<number>();
      return value.players.map((player: unknown): CatalogPlayer => {
        if (
          !record(player) ||
          typeof player.id !== "number" ||
          !Number.isSafeInteger(player.id) ||
          player.id < 1 ||
          seen.has(player.id) ||
          typeof player.name !== "string" ||
          !player.name.trim() ||
          typeof player.team !== "string"
        )
          throw new Error("Invalid player");
        seen.add(player.id);
        return { id: player.id, name: player.name, team: player.team };
      });
    },
    { signal },
  );
}

export class IntentError extends Error {
  readonly status: number;

  constructor(status: number) {
    super("The intent service refused the request.");
    this.status = status;
  }
}

export async function readIntent(
  origin: string,
  message: string,
  locale: Language,
  draft: PlanDraft,
  players: CatalogPlayer[],
  signal: AbortSignal,
  clarification?: Clarification,
  referenceWeeks?: readonly PlanWeekNumber[],
) {
  return withRequestDeadline(
    async (signal) => {
      const response = await fetch(`${origin}/api/v1/llmopt/intent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          locale,
          draft,
          players: players.map(({ team, ...player }) => ({
            ...player,
            ...(team.trim() ? { team } : {}),
          })),
          ...(clarification ? { clarification } : {}),
          ...(referenceWeeks?.length ? { reference_weeks: referenceWeeks } : {}),
        }),
        signal,
      });
      if (!response.ok) {
        await discardBody(response);
        throw new IntentError(response.status);
      }
      const value: unknown = await response.json();
      if (!record(value)) throw new Error("Invalid response");
      if (
        value.status === "clarification" &&
        typeof value.message === "string" &&
        value.message.trim()
      )
        return { status: "clarification" as const, message: value.message };
      if (value.status !== "draft") throw new Error("Invalid response");
      return {
        status: "draft" as const,
        draft: checkedDraft(value.draft, players),
      };
    },
    { signal, timeoutMs: 45_000 },
  );
}
