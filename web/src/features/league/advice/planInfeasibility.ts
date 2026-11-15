import { isPlanWeek, type PlanWeekNumber } from "./decisionPreferences";

export type PlanRepair =
  | { kind: "lower_bank_floor"; tenths: number }
  | {
      kind: "defer_purchase";
      player_id: number;
      from_week: PlanWeekNumber;
      to_week: PlanWeekNumber;
    }
  | { kind: "release_purchase"; player_id: number; week: PlanWeekNumber };

export interface PlanInfeasibility {
  repairs: PlanRepair[];
  bank?: { required: number; reachable: number; exact: boolean; week?: PlanWeekNumber };
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function amount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 10_000;
}

function checkedRepair(value: unknown): PlanRepair | undefined {
  if (!record(value)) return;
  const { kind, player_id, from_week, to_week, week, tenths } = value;
  if (kind === "lower_bank_floor" && Object.keys(value).length === 2 && amount(tenths))
    return { kind, tenths };
  if (typeof player_id !== "number" || !Number.isSafeInteger(player_id) || player_id <= 0) return;
  if (
    kind === "defer_purchase" &&
    Object.keys(value).length === 4 &&
    isPlanWeek(from_week) &&
    isPlanWeek(to_week) &&
    from_week < to_week
  )
    return { kind, player_id, from_week, to_week };
  if (kind === "release_purchase" && Object.keys(value).length === 3 && isPlanWeek(week))
    return { kind, player_id, week };
}

export function checkedPlanInfeasibility(value: unknown): PlanInfeasibility | undefined {
  if (!record(value) || Object.keys(value).some((key) => key !== "repairs" && key !== "bank"))
    return;
  if (!Array.isArray(value.repairs) || value.repairs.length > 3) return;
  const repairs = value.repairs.map(checkedRepair);
  if (
    repairs.some((repair) => repair === undefined) ||
    new Set(repairs.map((repair) => JSON.stringify(repair))).size !== repairs.length
  )
    return;
  let bank: PlanInfeasibility["bank"];
  if (value.bank !== undefined) {
    if (
      !record(value.bank) ||
      Object.keys(value.bank).some(
        (key) => key !== "required" && key !== "reachable" && key !== "exact" && key !== "week",
      )
    )
      return;
    const { required, reachable, exact, week } = value.bank;
    if (
      !amount(required) ||
      !amount(reachable) ||
      reachable >= required ||
      typeof exact !== "boolean" ||
      (week !== undefined && !isPlanWeek(week))
    )
      return;
    bank = { required, reachable, exact, ...(week === undefined ? {} : { week }) };
  }
  const validated = repairs.filter((repair) => repair !== undefined);
  if (
    validated.some(
      (repair) => repair.kind === "lower_bank_floor" && repair.tenths !== bank?.reachable,
    )
  )
    return;
  return { repairs: validated, ...(bank ? { bank } : {}) };
}
