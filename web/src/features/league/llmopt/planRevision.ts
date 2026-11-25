import type { FrozenPlanWeek, PlanWeekNumber } from "../advice/decisionPreferences";
import type { AdviceChip, AdvicePlayer, EntryAdvice } from "../types";
import { expectedNet, plannedWeeks, weekNet } from "./planComparison";

type TransferPlayer = Pick<AdvicePlayer, "player_id" | "name">;

interface RevisionWeek {
  net?: number;
  hits?: number;
  incoming: TransferPlayer[];
  outgoing: TransferPlayer[];
  chip: AdviceChip | null;
  bank?: number;
  freeTransfers?: number;
  lineup?: { starters: number[]; captain: number };
}

export interface PlanRevision {
  compareOnly?: true;
  gameweek: number;
  window: 1 | 3;
  net: number | null;
  weeks: RevisionWeek[];
}

function lineup(
  starters: AdvicePlayer[] | null | undefined,
  captain: AdvicePlayer | null | undefined,
) {
  if (!captain || starters?.length !== 11) return undefined;
  return { starters: starters.map(({ player_id }) => player_id), captain: captain.player_id };
}

function transferPlayer({ player_id, name }: TransferPlayer): TransferPlayer {
  return { player_id, name };
}

export function summarizeRevision(plan: EntryAdvice): PlanRevision | undefined {
  if (plan.window !== 1 && plan.window !== 3) return undefined;
  const weeks = plannedWeeks(plan)?.map((week, index): RevisionWeek => ({
    net: weekNet(week),
    hits: week.transfer_hit_points,
    incoming: week.transfers_in.map(transferPlayer),
    outgoing: week.transfers_out.map(transferPlayer),
    chip: week.chip,
    bank:
      week.bank_after_tenths ??
      (index === 0 && week.chip !== "freehit" ? plan.bank_after_tenths : undefined),
    freeTransfers: week.free_transfers_after,
    lineup: week.lineup
      ? lineup(week.lineup.starting_xi, week.lineup.captain)
      : index === 0
        ? lineup(plan.starting_xi, plan.captain)
        : undefined,
  })) ?? [
    {
      net: expectedNet(plan) ?? undefined,
      hits: plan.transfer_hit_points,
      incoming: plan.moves.flatMap(({ player_in }) =>
        player_in ? [transferPlayer(player_in)] : [],
      ),
      outgoing: plan.moves.flatMap(({ player_out }) =>
        player_out ? [transferPlayer(player_out)] : [],
      ),
      chip: plan.chip ?? null,
      bank: plan.chip === "freehit" ? undefined : plan.bank_after_tenths,
      freeTransfers: plan.free_transfers_after,
      lineup: lineup(plan.starting_xi, plan.captain),
    },
  ];
  return { gameweek: plan.gameweek, window: plan.window, net: expectedNet(plan), weeks };
}

function boundedInteger(value: unknown, minimum: number, maximum: number): value is number {
  return (
    typeof value === "number" && Number.isSafeInteger(value) && value >= minimum && value <= maximum
  );
}

function playerId(value: unknown): value is number {
  return boundedInteger(value, 1, Number.MAX_SAFE_INTEGER);
}

function playerList(value: unknown): value is TransferPlayer[] {
  return (
    Array.isArray(value) &&
    value.length <= 15 &&
    value.every((player: unknown) => {
      if (!player || typeof player !== "object") return false;
      const { player_id, name } = player as Partial<TransferPlayer>;
      return playerId(player_id) && typeof name === "string" && !!name.trim() && name.length <= 120;
    }) &&
    new Set(value.map(({ player_id }) => player_id)).size === value.length
  );
}

function checkedWeek(value: unknown): RevisionWeek | null {
  if (!value || typeof value !== "object") return null;
  const { incoming, outgoing, chip, bank, freeTransfers, lineup, net, hits } =
    value as Partial<RevisionWeek>;
  if (
    (net !== undefined && (typeof net !== "number" || !Number.isFinite(net))) ||
    (hits !== undefined && (typeof hits !== "number" || !Number.isFinite(hits) || hits < 0)) ||
    !playerList(incoming) ||
    !playerList(outgoing) ||
    incoming.length !== outgoing.length ||
    !(
      chip === null ||
      chip === "wildcard" ||
      chip === "freehit" ||
      chip === "bboost" ||
      chip === "3xc"
    ) ||
    (bank !== undefined && !boundedInteger(bank, 0, 10_000)) ||
    (freeTransfers !== undefined && !boundedInteger(freeTransfers, 0, 5))
  )
    return null;
  const starters = lineup?.starters;
  const captain = lineup?.captain;
  if (
    lineup !== undefined &&
    (!Array.isArray(starters) ||
      starters.length !== 11 ||
      new Set(starters).size !== 11 ||
      !starters.every(playerId) ||
      !playerId(captain) ||
      !starters.includes(captain))
  )
    return null;
  return {
    net,
    hits,
    incoming: incoming.map(transferPlayer),
    outgoing: outgoing.map(transferPlayer),
    chip,
    bank,
    freeTransfers,
    lineup,
  };
}

export function checkedPlanRevision(
  value: unknown,
  expectedGameweek: number,
): PlanRevision | undefined {
  if (!value || typeof value !== "object") return undefined;
  const { gameweek, window, weeks, net, compareOnly } = value as Partial<PlanRevision>;
  if (
    (compareOnly !== undefined && compareOnly !== true) ||
    gameweek !== expectedGameweek ||
    (window !== 1 && window !== 3) ||
    (net !== null && (typeof net !== "number" || !Number.isFinite(net))) ||
    !Array.isArray(weeks) ||
    (weeks.length !== 1 && weeks.length !== window)
  )
    return undefined;
  const checked = weeks.map(checkedWeek);
  if (!checked.every((week) => week !== null)) return undefined;
  return { gameweek, window, net, weeks: checked, ...(compareOnly ? { compareOnly } : {}) };
}

export function referenceWeeks(reference?: PlanRevision): PlanWeekNumber[] | undefined {
  return reference?.weeks.map((_, index) => (index + 1) as PlanWeekNumber);
}

export function referenceCaptains(reference?: PlanRevision) {
  return referenceWeeks(reference)?.flatMap((week) => {
    const captain = reference?.weeks[week - 1]?.lineup?.captain;
    return captain === undefined ? [] : [{ week, player_id: captain }];
  });
}

export function freezeReference(
  reference: PlanRevision | undefined,
  selected: readonly PlanWeekNumber[] = [],
): FrozenPlanWeek[] {
  return selected.flatMap((relativeWeek) => {
    const week = reference?.weeks[relativeWeek - 1];
    return week
      ? [
          {
            week: relativeWeek,
            transfers_in: week.incoming.map(({ player_id }) => player_id),
            transfers_out: week.outgoing.map(({ player_id }) => player_id),
            chip: week.chip,
            ...(week.lineup
              ? { starting_xi: week.lineup.starters, captain: week.lineup.captain }
              : {}),
          },
        ]
      : [];
  });
}
