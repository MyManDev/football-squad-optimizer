import type { FrozenPlanWeek, PlanWeekNumber } from "../advice/decisionPreferences";
import { ruleLabel, type LLMOptCopy } from "./copy";
import type { CatalogPlayer, Constraint, PlanDraft } from "./intent";

interface ConflictContext {
  gameweek: number;
  window: 1 | 3;
  held: ReadonlySet<number>;
  frozen: readonly FrozenPlanWeek[];
  players: readonly CatalogPlayer[];
  copy: LLMOptCopy;
}

function frozenConflict(rule: Constraint, frozen: FrozenPlanWeek) {
  switch (rule.kind) {
    case "buy_player":
      return !frozen.transfers_in.includes(rule.player_id);
    case "avoid_player":
      return (
        frozen.transfers_in.includes(rule.player_id) || frozen.starting_xi?.includes(rule.player_id)
      );
    case "include_player":
    case "keep_player":
      return frozen.transfers_out.includes(rule.player_id);
    case "hold_transfers":
      return frozen.transfers_in.length > 0 || frozen.chip === "wildcard";
    case "save_chips":
      return frozen.chip !== null;
    case "wildcard":
      return frozen.chip !== "wildcard";
    default:
      return false;
  }
}

export function explainDraftConflict(
  draft: PlanDraft,
  context: ConflictContext,
): string | undefined {
  const { gameweek, window, held, frozen, players, copy } = context;
  const absolute = (week: number) => gameweek + week - 1;
  const label = (rule: Constraint) => ruleLabel(rule, players, copy);
  const name = (id: number) => players.find((player) => player.id === id)?.name ?? String(id);
  const pair = (week: PlanWeekNumber, first: Constraint, second: Constraint) =>
    copy.conflictingRules(absolute(week), label(first), label(second));

  const missing = draft.keep_weeks?.find((week) => !frozen.some((row) => row.week === week));
  if (missing) return copy.missingFrozenWeek(absolute(missing));
  const keep = draft.hard.find((rule) => rule.kind === "keep_player" && !held.has(rule.player_id));
  if (keep?.kind === "keep_player") return copy.keepUnowned(name(keep.player_id));
  const wildcardWeeks = draft.hard.filter(({ kind }) => kind === "wildcard");
  const wildcard = wildcardWeeks[0];
  const conflictingWildcard = wildcardWeeks.find(
    (rule) => (rule.week ?? 1) !== (wildcard?.week ?? 1),
  );
  if (wildcard && conflictingWildcard)
    return pair(conflictingWildcard.week ?? 1, conflictingWildcard, wildcard);

  let initialSquadUnchanged = true;
  for (const week of [1, 2, 3] as const) {
    if (week > window) break;
    const rules = draft.hard.filter((rule) =>
      rule.kind === "wildcard"
        ? (rule.week ?? 1) === week
        : rule.week === undefined || rule.week === week,
    );
    const fixed = frozen.find((row) => row.week === week);
    const conflictingRule = fixed && rules.find((rule) => frozenConflict(rule, fixed));
    if (conflictingRule) return copy.frozenRuleConflict(absolute(week), label(conflictingRule));

    const hold = rules.find(({ kind }) => kind === "hold_transfers");
    const save = rules.find(({ kind }) => kind === "save_chips");
    const play = rules.find(({ kind }) => kind === "wildcard");
    if (play && save) return pair(week, play, save);
    if (play && hold) return pair(week, play, hold);
    for (const rule of rules) {
      if (rule.kind === "buy_player" && week === 1 && held.has(rule.player_id))
        return copy.buyAlreadyHeld(absolute(week), name(rule.player_id));
      if (
        hold &&
        (rule.kind === "buy_player" ||
          (rule.kind === "club_count" && rule.scope === "transfers_in"))
      )
        return pair(week, rule, hold);
      if (rule.kind === "club_count") {
        const incompatible = rules.find(
          (other) =>
            other.kind === "club_count" &&
            other.club === rule.club &&
            (other.scope ?? "squad") === (rule.scope ?? "squad") &&
            other.count !== rule.count,
        );
        if (incompatible) return pair(week, rule, incompatible);
      }
      if (
        rule.kind === "keep_player" ||
        rule.kind === "include_player" ||
        rule.kind === "buy_player"
      ) {
        const exclusion = rules.find(
          (other) => other.kind === "avoid_player" && other.player_id === rule.player_id,
        );
        if (exclusion) return pair(week, rule, exclusion);
      }
      if (
        hold &&
        initialSquadUnchanged &&
        ((rule.kind === "include_player" && !held.has(rule.player_id)) ||
          (rule.kind === "avoid_player" && held.has(rule.player_id)))
      )
        return pair(week, rule, hold);
    }
    initialSquadUnchanged = initialSquadUnchanged && !!hold;
  }
  return undefined;
}
