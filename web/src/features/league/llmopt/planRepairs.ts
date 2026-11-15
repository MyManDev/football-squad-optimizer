import type { AdviceRequest } from "../advice/adviceClient";
import type { PlanRepair } from "../advice/planInfeasibility";
import { checkedDraft, type CatalogPlayer, type Constraint, type PlanDraft } from "./intent";

function repairDraft(
  draft: PlanDraft,
  request: AdviceRequest,
  repair: PlanRepair,
): PlanDraft | undefined {
  if (repair.kind === "lower_bank_floor") {
    const original = draft.min_bank;
    const requested = request.preferences?.min_bank;
    if (
      !original ||
      !requested ||
      original.tenths !== requested.tenths ||
      original.week !== requested.week ||
      repair.tenths >= original.tenths
    )
      return undefined;
    return {
      ...draft,
      min_bank: repair.tenths === 0 ? undefined : { ...original, tenths: repair.tenths },
    };
  }
  const week = repair.kind === "defer_purchase" ? repair.from_week : repair.week;
  const weekRules = request.preferences?.week_rules?.find((row) => row.week === week)?.rules;
  if (!weekRules?.buy_players?.includes(repair.player_id)) return undefined;
  if (
    repair.kind === "defer_purchase" &&
    (repair.to_week <= week || repair.to_week > request.window)
  )
    return undefined;
  const matches = (rule: Constraint): rule is Extract<Constraint, { kind: "buy_player" }> =>
    rule.kind === "buy_player" && rule.player_id === repair.player_id && rule.week === week;
  for (const strength of ["hard", "soft"] as const) {
    if (!draft[strength].some(matches)) continue;
    const rules = draft[strength].flatMap<Constraint>((rule) => {
      if (!matches(rule)) return [rule];
      return repair.kind === "defer_purchase" ? [{ ...rule, week: repair.to_week }] : [];
    });
    return { ...draft, [strength]: rules };
  }
  if (draft.comparison?.kind === "buy_player" && matches(draft.comparison)) {
    return {
      ...draft,
      comparison:
        repair.kind === "defer_purchase"
          ? { ...draft.comparison, week: repair.to_week }
          : undefined,
    };
  }
  return undefined;
}

export function repairOptions(
  draft: PlanDraft,
  request: AdviceRequest,
  repairs: readonly PlanRepair[],
  players: readonly CatalogPlayer[],
) {
  return repairs.flatMap((repair) => {
    const next = repairDraft(draft, request, repair);
    if (!next) return [];
    try {
      return [{ repair, draft: checkedDraft(next, players) }];
    } catch {
      return [];
    }
  });
}
