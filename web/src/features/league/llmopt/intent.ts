import { discardBody, withRequestDeadline } from "../../../data/request";
import type { Language } from "../../../i18n/messages";
import {
  checkedPreferences,
  clubCountKey,
  clubCountsConflict,
  preferencesKey,
  type ClubCount,
  type DecisionPreferences,
} from "../advice/decisionPreferences";

const playerKinds = ["keep_player", "include_player", "avoid_player"] as const;
const ruleKinds = ["hold_transfers", "no_hits", "save_chips", "wildcard"] as const;

export const CONSTRAINT_KINDS = [...ruleKinds, ...playerKinds, "club_count"] as const;
export const MAX_CONSTRAINTS = 16;
export const MAX_MESSAGE_LENGTH = 800;

export type Constraint =
  | { kind: (typeof playerKinds)[number]; player_id: number }
  | { kind: (typeof ruleKinds)[number] }
  | ({ kind: "club_count" } & ClubCount);
type Comparison = Constraint & { both?: boolean };

export interface PlanDraft {
  hard: Constraint[];
  soft: Constraint[];
  comparison?: Comparison;
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

export function isPlayerKind(kind: Constraint["kind"]): kind is (typeof playerKinds)[number] {
  return kind === "keep_player" || kind === "include_player" || kind === "avoid_player";
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function parseConstraint(
  value: unknown,
  players: ReadonlySet<number>,
  clubs: ReadonlySet<string>,
  comparison = false,
) {
  if (
    !record(value) ||
    !CONSTRAINT_KINDS.some((kind) => kind === value.kind) ||
    Object.keys(value).some(
      (key) =>
        !["kind", "player_id", "club", "count", "scope"].includes(key) &&
        !(comparison && key === "both"),
    )
  )
    throw new Error("Invalid constraint");
  const kind = value.kind as Constraint["kind"];
  const id = value.player_id;
  const { club, count, scope } = value;
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
    } satisfies Constraint;
  }
  if (club !== undefined || count !== undefined || scope !== undefined)
    throw new Error("Unexpected club count");
  if (isPlayerKind(kind)) {
    if (typeof id !== "number" || !players.has(id)) throw new Error("Unknown player");
    return { kind, player_id: id } satisfies Constraint;
  }
  if (id !== undefined) throw new Error("Unexpected player");
  return { kind } satisfies Constraint;
}

function parseDraft(
  value: unknown,
  playerIds: ReadonlySet<number>,
  clubs: ReadonlySet<string>,
): PlanDraft {
  if (
    !record(value) ||
    !Array.isArray(value.hard) ||
    !Array.isArray(value.soft) ||
    value.hard.length + value.soft.length > MAX_CONSTRAINTS
  )
    throw new Error("Invalid draft");
  const draft: PlanDraft = {
    hard: value.hard.map((item) => parseConstraint(item, playerIds, clubs)),
    soft: value.soft.map((item) => parseConstraint(item, playerIds, clubs)),
  };
  const keys = [...draft.hard, ...draft.soft].map(constraintKey);
  if (new Set(keys).size !== keys.length) throw new Error("Repeated constraint");
  if (value.comparison != null) {
    const item = parseConstraint(value.comparison, playerIds, clubs, true);
    const both = (value.comparison as Record<string, unknown>).both;
    if (both != null && (typeof both !== "boolean" || (both && item.kind !== "include_player")))
      throw new Error("Invalid comparison");
    draft.comparison = both === true ? { ...item, both: true } : item;
  }
  return draft;
}

export function constraintKey(rule: Constraint): string {
  if (rule.kind === "club_count") return `${rule.kind}:${clubCountKey(rule)}:${rule.count}`;
  return "player_id" in rule ? `${rule.kind}:${rule.player_id}` : rule.kind;
}

function playerIds(rules: readonly Constraint[], kind: (typeof playerKinds)[number]) {
  return [...new Set(rules.flatMap((rule) => (rule.kind === kind ? [rule.player_id] : [])))];
}

function branchSelection(rules: readonly Constraint[]): PreparedPlan {
  const chip = rules.some(({ kind }) => kind === "wildcard") ? "wildcard" : null;
  return {
    chip,
    preferences: checkedPreferences({
      keep_players: playerIds(rules, "keep_player"),
      include_players: playerIds(rules, "include_player"),
      avoid_players: playerIds(rules, "avoid_player"),
      no_hits: rules.some(({ kind }) => kind === "no_hits"),
      hold_transfers: rules.some(({ kind }) => kind === "hold_transfers"),
      save_chips: chip === null,
      club_counts: clubCounts(rules),
    }),
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

function conflicts(rules: readonly Constraint[], held: ReadonlySet<number>) {
  const owned = playerIds(rules, "keep_player");
  const included = [...owned, ...playerIds(rules, "include_player")];
  const excluded = playerIds(rules, "avoid_player");
  const counts = clubCounts(rules);
  const holdsTransfers = rules.some(({ kind }) => kind === "hold_transfers");
  return (
    owned.some((id) => !held.has(id)) ||
    new Set(included).size > 15 ||
    excluded.length > 15 ||
    counts.length > MAX_CONSTRAINTS ||
    clubCountsConflict(counts, holdsTransfers) ||
    included.some((id) => excluded.includes(id)) ||
    (holdsTransfers &&
      (included.some((id) => !held.has(id)) || excluded.some((id) => held.has(id)))) ||
    (rules.some(({ kind }) => kind === "wildcard") &&
      (holdsTransfers || rules.some(({ kind }) => kind === "save_chips")))
  );
}

export function preparePlans(draft: PlanDraft, held: ReadonlySet<number>) {
  const both = draft.comparison?.kind === "include_player" && draft.comparison.both;
  const baseRules: Constraint[] =
    both && draft.comparison?.kind === "include_player"
      ? [...draft.hard, { kind: "avoid_player", player_id: draft.comparison.player_id }]
      : draft.hard;
  const alternativeRules = [...draft.hard, ...(draft.comparison ? [draft.comparison] : draft.soft)];
  const baseConflict = conflicts(baseRules, held);
  const alternativeConflict = conflicts(alternativeRules, held);
  const base = baseConflict ? null : branchSelection(baseRules);
  const alternative = alternativeConflict ? null : branchSelection(alternativeRules);
  return {
    base,
    alternative:
      alternative &&
      (!base ||
        base.chip !== alternative.chip ||
        preferencesKey(base.preferences) !== preferencesKey(alternative.preferences))
        ? alternative
        : null,
    hardConflict: conflicts(draft.hard, held),
    baseConflict,
    alternativeConflict,
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
        draft: parseDraft(
          value.draft,
          new Set(players.map(({ id }) => id)),
          new Set(players.map(({ team }) => team).filter(Boolean)),
        ),
      };
    },
    { signal, timeoutMs: 45_000 },
  );
}
