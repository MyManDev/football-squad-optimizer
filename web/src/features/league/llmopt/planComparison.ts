import type { AdviceRequest } from "../advice/adviceClient";
import {
  checkedPreferences,
  holdsOpeningTransfers,
  type DecisionPreferences,
} from "../advice/decisionPreferences";
import type { ComputePhase } from "../advice/useAdviceJob";
import type { AdvicePlanWeek, EntryAdvice } from "../types";

export function plannedWeeks(plan: EntryAdvice) {
  const weeks = [...(plan.plan_weeks ?? [])].sort((a, b) => a.gameweek - b.gameweek);
  return weeks.length === plan.window &&
    weeks.every((week, index) => week.gameweek === plan.gameweek + index)
    ? weeks
    : null;
}

export function weekNet(week: AdvicePlanWeek) {
  return week.expected_points - week.transfer_hit_points;
}

export function expectedNet(plan: EntryAdvice) {
  if (plan.window > 1)
    return plannedWeeks(plan)?.reduce((sum, week) => sum + weekNet(week), 0) ?? null;
  const week = plan.plan_weeks?.find((row) => row.gameweek === plan.gameweek);
  if (week) return weekNet(week);
  if (plan.lineup_expectation) return plan.lineup_expectation.expected_net_points;
  return plan.expected_own_points != null && plan.transfer_hit_points != null
    ? plan.expected_own_points - plan.transfer_hit_points
    : null;
}

function openingAction(plan: EntryAdvice) {
  const week = plan.plan_weeks?.find((row) => row.gameweek === plan.gameweek);
  const incoming = week
    ? week.transfers_in.map(({ player_id }) => player_id)
    : plan.moves.flatMap(({ player_in }) => (player_in ? [player_in.player_id] : []));
  const outgoing = week
    ? week.transfers_out.map(({ player_id }) => player_id)
    : plan.moves.flatMap(({ player_out }) => (player_out ? [player_out.player_id] : []));
  return {
    incoming: incoming.sort((a, b) => a - b),
    outgoing: outgoing.sort((a, b) => a - b),
    chip: week ? week.chip : (plan.chip ?? null),
    bank: plan.bank_after_tenths,
    free: week?.free_transfers_after ?? plan.free_transfers_after,
    hits: week?.transfer_hit_points ?? plan.transfer_hit_points,
  };
}

export type OpeningAlternativeGoal = "roll" | "bank";

export function openingAlternatives(
  plan: EntryAdvice,
  reference: DecisionPreferences,
  chip: AdviceRequest["chip"],
): Record<OpeningAlternativeGoal, DecisionPreferences | null> {
  if (reference.frozen_weeks?.some(({ week }) => week === 1)) return { roll: null, bank: null };
  const opening = openingAction(plan);
  const week = reference.week_rules?.find(({ week }) => week === 1)?.rules;
  const alreadyHolds = holdsOpeningTransfers(reference);
  const forcedChange =
    Boolean(week?.buy_players?.length) ||
    [reference, week].some(
      (rules) =>
        rules?.club_counts?.some(({ scope }) => scope === "transfers_in") ||
        rules?.include_players?.some((id) => opening.incoming.includes(id)) ||
        rules?.avoid_players.some((id) => opening.outgoing.includes(id)),
    );
  const canRoll =
    (opening.incoming.length > 0 || opening.outgoing.length > 0) &&
    !alreadyHolds &&
    !forcedChange &&
    opening.chip !== "wildcard" &&
    opening.chip !== "freehit" &&
    chip !== "auto" &&
    chip !== "wildcard" &&
    chip !== "freehit";
  const bank = opening.bank;
  const bankFloor =
    bank === undefined ? null : Math.max(bank + 1, reference.min_opening_bank_tenths ?? 1);
  return {
    roll: canRoll ? checkedPreferences({ ...reference, hold_opening_transfers: true }) : null,
    bank:
      !alreadyHolds &&
      bankFloor !== null &&
      Number.isInteger(bankFloor) &&
      bankFloor > 0 &&
      bankFloor <= 10_000
        ? checkedPreferences({ ...reference, min_opening_bank_tenths: bankFloor })
        : null,
  };
}

/** The transfers and chip are the opening decision. Move pairing and lineups do not change it. */
export function sameOpeningDecision(first: EntryAdvice, second: EntryAdvice) {
  const key = (plan: EntryAdvice) => {
    const { incoming, outgoing, chip } = openingAction(plan);
    return JSON.stringify([plan.gameweek, incoming, outgoing, chip]);
  };
  return key(first) === key(second);
}

export function meaningfulOpeningAlternative(
  reference: EntryAdvice,
  candidate: EntryAdvice,
  goal: OpeningAlternativeGoal,
) {
  if (
    reference.window !== candidate.window ||
    reference.gameweek !== candidate.gameweek ||
    reference.season !== candidate.season ||
    reference.league_id !== candidate.league_id ||
    reference.entry_id !== candidate.entry_id ||
    reference.source_snapshot_id !== candidate.source_snapshot_id ||
    sameOpeningDecision(reference, candidate)
  )
    return false;
  const base = openingAction(reference);
  const alternative = openingAction(candidate);
  if (goal === "bank")
    return (
      base.bank !== undefined && alternative.bank !== undefined && alternative.bank > base.bank
    );
  return (
    alternative.incoming.length === 0 &&
    alternative.outgoing.length === 0 &&
    ((base.free !== undefined && alternative.free !== undefined && alternative.free > base.free) ||
      (base.hits !== undefined && alternative.hits !== undefined && alternative.hits < base.hits))
  );
}

function action(plan: EntryAdvice) {
  const { incoming, outgoing, chip } = openingAction(plan);
  const later = plannedWeeks(plan)
    ?.slice(1)
    .map((week) => [
      week.gameweek,
      week.transfers_out.map(({ player_id }) => player_id).sort((a, b) => a - b),
      week.transfers_in.map(({ player_id }) => player_id).sort((a, b) => a - b),
      week.chip,
    ]);
  return JSON.stringify([plan.gameweek, plan.window, incoming, outgoing, chip, later]);
}

export function samePlan(first: ComputePhase, second: ComputePhase) {
  return (
    first.phase === "done" &&
    second.phase === "done" &&
    action(first.envelope.payload) === action(second.envelope.payload)
  );
}
