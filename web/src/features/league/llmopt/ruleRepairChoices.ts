import type { Language } from "../../../i18n/messages";
import { money } from "../../../lib/format";
import type { AdviceRequest } from "../advice/adviceClient";
import type { FrozenPlanWeek, PlanWeekNumber } from "../advice/decisionPreferences";
import type { PlanInfeasibility } from "../advice/planInfeasibility";
import { LLMOPT_COPY, ruleLabel } from "./copy";
import { type CatalogPlayer, type Constraint, type PlanDraft } from "./intent";
import { explainDraftConflict, frozenConflict } from "./planConflicts";
import { repairOptions } from "./planRepairs";

export type RepairStatus = "conflict" | "missing" | "budget";

export interface RepairChoice {
  draft: PlanDraft;
  label: string;
}

export interface RuleRepairContext {
  gameweek: number;
  window: 1 | 3;
  held: ReadonlySet<number>;
  /** Clubs from the same capture as the member's squad. */
  heldClubs?: ReadonlyMap<number, string>;
  players: readonly CatalogPlayer[];
  frozen: readonly FrozenPlanWeek[];
  language: Language;
  /** Omit until checked; null means the entry's chip history is missing. */
  heldChips?: readonly string[] | null;
  freeTransfers?: number | null;
  hitPoints?: number | null;
  bankTenths?: number | null;
  completeRoster?: boolean;
  diagnosis?: PlanInfeasibility | null;
  request?: AdviceRequest;
  failureCode?: string | null;
}

export function repairSentence(language: Language, status: RepairStatus | "wait") {
  return LLMOPT_COPY[language].repairs[status];
}

const missingCodes = new Set([
  "INPUTS_UNAVAILABLE",
  "MODEL_INPUTS_UNAVAILABLE",
  "TOP100_INPUTS_UNAVAILABLE",
  "MANAGERS_WORD_UNAVAILABLE",
  "PROJECTION_UNAVAILABLE",
  "CONTEXT_UNAVAILABLE",
  "ENTRY_NOT_IN_CAPTURE",
  "PUBLIC_ENTRY_INPUTS_UNAVAILABLE",
  "DEVICE_INPUTS_UNAVAILABLE",
  "CHIP_HISTORY_UNKNOWN",
]);

export function isMissingRepairInput(code: string) {
  return missingCodes.has(code);
}

/** Candidates describe one hard-rule edit. Only a completed plan can make one selectable. */
export function ruleRepairChoices(draft: PlanDraft, context: RuleRepairContext) {
  const { language, gameweek, window, frozen, held, players, diagnosis, failureCode } = context;
  const copy = LLMOPT_COPY[language];
  const outcome = (
    status: RepairStatus,
    choices: RepairChoice[] = [],
    sentence = repairSentence(language, status),
  ) => ({
    status,
    sentence,
    choices: choices.slice(0, 2),
  });
  if (failureCode === "RUN_BUDGET_EXHAUSTED") return outcome("budget");
  if (failureCode === "PATIENCE_EXHAUSTED")
    return outcome("budget", [], repairSentence(language, "wait"));
  if (failureCode && missingCodes.has(failureCode)) return outcome("missing");
  if (
    failureCode &&
    failureCode !== "CHIP_NOT_HELD" &&
    failureCode !== "DEVICE_PLAN_INFEASIBLE" &&
    !(failureCode === "PLAN_NOT_FOUND" && diagnosis)
  )
    return null;

  const wildcard = draft.hard.find((r) => r.kind === "wildcard");
  if (draft.keep_weeks?.some((week) => !frozen.some((f) => f.week === week)))
    return outcome("missing");
  if (wildcard && context.heldChips === null && failureCode !== "CHIP_NOT_HELD")
    return outcome("missing");
  const known: RepairChoice[] = [];
  const possible: RepairChoice[] = [];
  let conflictSentence: string | undefined;
  const tr = language === "tr";
  function editRule(index: number, replacement?: Constraint): RepairChoice {
    const before = ruleLabel(draft.hard[index]!, players, copy);
    const after = replacement && ruleLabel(replacement, players, copy);
    return {
      draft: {
        ...draft,
        hard: draft.hard.flatMap((rule, i) =>
          i !== index ? [rule] : replacement ? [replacement] : [],
        ),
      },
      label: after ? copy.repairs.changeRule(before, after) : copy.repairs.removeRule(before),
    };
  }
  const applies = (r: Constraint, week: PlanWeekNumber) =>
    r.kind === "wildcard" ? (r.week ?? 1) === week : r.week === undefined || r.week === week;
  const opening = draft.hard.filter((r) => applies(r, 1));
  const requiredBuys = new Set(
    opening.flatMap((r) =>
      (r.kind === "include_player" || r.kind === "buy_player") && !held.has(r.player_id)
        ? [r.player_id]
        : [],
    ),
  );
  const openingRebuild =
    opening.some((r) => r.kind === "wildcard") ||
    frozen.some((f) => f.week === 1 && (f.chip === "freehit" || f.chip === "wildcard"));
  const paid =
    context.freeTransfers == null || openingRebuild
      ? 0
      : Math.max(0, requiredBuys.size - context.freeTransfers);
  const minimumHits = context.hitPoints != null ? paid * context.hitPoints : undefined;
  const locked = (week: number) =>
    Array.from({ length: week }, (_, i) => i + 1).every((n) =>
      draft.hard.some((r) => r.kind === "hold_transfers" && (r.week === undefined || r.week === n)),
    );
  const bank = draft.min_bank;
  if (bank) {
    const observed = diagnosis?.bank;
    const atWeek = bank.week ?? window;
    const reachable =
      observed?.required === bank.tenths && observed.week === bank.week
        ? observed.reachable
        : locked(atWeek)
          ? context.bankTenths
          : undefined;
    const target = reachable == null ? 0 : reachable;
    if (target < bank.tenths) {
      if (reachable != null) {
        const amount = money(bank.tenths, tr ? "tr-TR" : "en-GB");
        conflictSentence = copy.repairs.bank(amount, gameweek + atWeek - 1);
      }
      const label = target
        ? copy.lowerBankMinimum(money(target, tr ? "tr-TR" : "en-GB"))
        : copy.removeBankMinimum;
      const next = { ...draft };
      if (target) next.min_bank = { ...bank, tenths: target };
      else delete next.min_bank;
      (reachable == null ? possible : known).push({
        draft: next,
        label: `${label} · ${bank.week ? copy.bankAfterWeek(gameweek + atWeek - 1) : copy.bankAfterFinal}`,
      });
    }
  }
  for (const fixed of frozen) {
    if (!draft.keep_weeks?.includes(fixed.week)) continue;
    const conflict = draft.hard.some(
      (rule) => applies(rule, fixed.week) && frozenConflict(rule, fixed),
    );
    const remainder = draft.keep_weeks.filter((n) => n !== fixed.week);
    const next = { ...draft };
    if (remainder.length) next.keep_weeks = remainder;
    else delete next.keep_weeks;
    const week = gameweek + fixed.week - 1;
    if (conflict) conflictSentence ??= copy.repairs.frozen(week);
    (conflict ? known : possible).push({
      draft: next,
      label: copy.repairs.unlock(week),
    });
  }
  draft.hard.forEach((rule, index) => {
    if (rule.kind === "wildcard") {
      const notHeld =
        failureCode === "CHIP_NOT_HELD" ||
        ((rule.week ?? 1) === 1 &&
          context.heldChips != null &&
          !context.heldChips.includes("wildcard"));
      const overlaps = draft.hard.some(
        (other) =>
          (other.kind === "save_chips" || other.kind === "hold_transfers") &&
          applies(other, rule.week ?? 1),
      );
      if (notHeld || overlaps) {
        const week = gameweek + (rule.week ?? 1) - 1;
        conflictSentence ??= copy.repairs.wildcard(week);
      }
      (notHeld || overlaps ? known : possible).push(editRule(index));
    } else if (rule.kind === "no_hits" || rule.kind === "hit_budget") {
      const ceiling = rule.kind === "hit_budget" ? rule.points : 0;
      const incompatible =
        applies(rule, 1) &&
        paid > 0 &&
        (rule.kind === "no_hits" || (minimumHits !== undefined && minimumHits > ceiling));
      if (incompatible)
        conflictSentence ??=
          ceiling === 0 ? copy.repairs.noHits(gameweek) : copy.repairs.hitLimit(gameweek, ceiling);
      const raised =
        rule.kind === "hit_budget" &&
        minimumHits !== undefined &&
        minimumHits > ceiling &&
        minimumHits <= 60
          ? { ...rule, points: minimumHits }
          : undefined;
      (incompatible ? known : possible).push(editRule(index, raised));
    } else if (rule.kind === "club_count") {
      const week = rule.week ?? 1;
      const others = draft.hard.filter((r) => r !== rule && applies(r, week));
      const incoming = rule.scope === "transfers_in";
      const clubPlayers = players.filter((p) => p.team === rule.club);
      const sameScope = others.some(
        (r) =>
          r.kind === "club_count" &&
          r.club === rule.club &&
          (r.scope ?? "squad") === (rule.scope ?? "squad") &&
          r.count !== rule.count,
      );
      const forced = new Set(
        others.flatMap((r) =>
          (r.kind === "buy_player" ||
            (!incoming && (r.kind === "include_player" || r.kind === "keep_player"))) &&
          (context.heldClubs?.get(r.player_id) === rule.club ||
            (context.completeRoster && clubPlayers.some((p) => p.id === r.player_id)))
            ? [r.player_id]
            : [],
        ),
      );
      const heldCount =
        context.heldClubs && [...held].every((id) => context.heldClubs!.has(id))
          ? [...held].filter((id) => context.heldClubs!.get(id) === rule.club).length
          : undefined;
      const fixedCount = locked(week) ? (incoming ? 0 : heldCount) : undefined;
      const feasibleCount =
        fixedCount ??
        (forced.size > rule.count
          ? forced.size
          : context.completeRoster && clubPlayers.length < rule.count
            ? clubPlayers.length
            : undefined);
      const incompatible =
        sameScope || (feasibleCount !== undefined && feasibleCount !== rule.count);
      if (incompatible) {
        const name = ruleLabel(rule, players, copy);
        conflictSentence ??= copy.repairs.club(name);
      }
      const change =
        !sameScope &&
        feasibleCount !== undefined &&
        feasibleCount >= 1 &&
        feasibleCount <= 3 &&
        feasibleCount !== rule.count
          ? { ...rule, count: feasibleCount }
          : undefined;
      (incompatible ? known : possible).push(editRule(index, change));
    }
  });
  if (diagnosis && context.request) {
    const purchases = diagnosis.repairs.filter((repair) => repair.kind !== "lower_bank_floor");
    const recommended = repairOptions(draft, context.request, purchases, players).flatMap(
      ({ repair, draft: next }) => {
        if (repair.kind === "lower_bank_floor") return [];
        const from = repair.kind === "defer_purchase" ? repair.from_week : repair.week;
        if (
          !draft.hard.some(
            (r) => r.kind === "buy_player" && r.week === from && r.player_id === repair.player_id,
          )
        )
          return [];
        const name = players.find((p) => p.id === repair.player_id)?.name;
        if (!name) return [];
        const week = gameweek + from - 1;
        const label =
          repair.kind === "defer_purchase"
            ? copy.deferPurchase(name, week, gameweek + repair.to_week - 1)
            : copy.releasePurchase(name, week);
        return [{ draft: next, label }];
      },
    );
    known.push(...recommended);
  }
  if (known.length) return outcome("conflict", known, conflictSentence);
  if (diagnosis || failureCode === "DEVICE_PLAN_INFEASIBLE") return outcome("conflict", possible);
  return explainDraftConflict(draft, { ...context, copy }) ? outcome("conflict") : null;
}
