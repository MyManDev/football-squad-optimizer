/** A preference job's request and computed components; no provider-produced results. */
import type { EntryAdvice } from "../types";
import type { MemberChip } from "./chipChoice";
import { checkedPlanInfeasibility, type PlanInfeasibility } from "./planInfeasibility";
import {
  checkedPreferences,
  preferencesKey,
  type DecisionPreferences,
} from "./decisionPreferences";

export const PREFERENCE_BUNDLE_VERSION = "llmopt_preference_bundle_v1";
export interface PreferenceSelection {
  preferences: Record<string, unknown>;
  chip: MemberChip | null;
}
export interface PriorityProgram {
  preferences: { rules: DecisionPreferences; priority: 1 | 2 | 3 }[];
  max_total_cost_tenths: number;
}
export interface PreferenceBundle {
  contract_version: typeof PREFERENCE_BUNDLE_VERSION;
  slots: (PreferenceSelection | null)[];
  prices: {
    outcome: number | "same" | "conflict" | "unavailable" | "skipped";
    ceiling: number | null;
  }[];
  choices: { accepted: number; applied: number[]; selection: PreferenceSelection | null }[];
  program: PriorityProgram | null;
}
export interface PreferenceComponent {
  infeasibility?: PlanInfeasibility;
  status: "done" | "failed" | "exhausted" | "unavailable";
  payload: EntryAdvice | null;
  error_code: string | null;
}
export interface PriorityResult {
  contract_version: "llmopt_priority_result_v1";
  satisfied: string[];
  left_out: string[];
  total_cost: number;
  completed_priorities: (1 | 2 | 3)[];
  reference_proved: boolean;
  budget_exhausted: boolean;
}
export interface PreferenceBundleResult {
  contract_version: "llmopt_preference_result_v1";
  request: PreferenceBundle;
  components: PreferenceComponent[];
  selected: PreferenceComponent | null;
  applied: number[];
  accepted: number;
  budget_exhausted: boolean;
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function closed(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return (
    record(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.hasOwn(value, key))
  );
}

const preferenceKeys = [
  "keep_players",
  "avoid_players",
  "no_hits",
  "save_chips",
  "hold_transfers",
  "include_players",
  "club_counts",
  "week_rules",
  "max_hit_points",
  "wildcard_week",
  "hold_opening_transfers",
  "min_opening_bank_tenths",
  "net_points_priority",
  "frozen_weeks",
  "min_bank",
  "scenario",
];
const boundedInteger = (value: unknown, maximum: number) =>
  Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= maximum;

function isSelection(value: unknown): value is PreferenceSelection {
  if (
    !closed(value, ["preferences", "chip"]) ||
    !record(value.preferences) ||
    ![null, "wildcard", "freehit", "3xc", "bboost"].includes(value.chip as MemberChip | null) ||
    Object.keys(value.preferences).some((key) => !preferenceKeys.includes(key))
  )
    return false;
  try {
    expandSelection(undefined, value as unknown as PreferenceSelection);
    return true;
  } catch {
    return false;
  }
}

function isBundle(value: unknown): value is PreferenceBundle {
  if (
    !closed(value, ["contract_version", "slots", "prices", "choices", "program"]) ||
    value.contract_version !== PREFERENCE_BUNDLE_VERSION ||
    !Array.isArray(value.slots) ||
    value.slots.length > 2 ||
    !value.slots.every((row) => row === null || isSelection(row)) ||
    !Array.isArray(value.prices) ||
    value.prices.length > 16 ||
    !value.prices.every(
      (row) =>
        closed(row, ["outcome", "ceiling"]) &&
        (["same", "conflict", "unavailable", "skipped"].includes(String(row.outcome)) ||
          boundedInteger(row.outcome, (value.slots as unknown[]).length - 1)) &&
        (row.ceiling === null || boundedInteger(row.ceiling, 1000)),
    ) ||
    !Array.isArray(value.choices) ||
    value.choices.length > 289 ||
    !value.choices.every(
      (row) =>
        closed(row, ["accepted", "applied", "selection"]) &&
        boundedInteger(row.accepted, 2 ** (value.prices as unknown[]).length - 1) &&
        Array.isArray(row.applied) &&
        row.applied.length <= 16 &&
        new Set(row.applied).size === row.applied.length &&
        row.applied.every((index) =>
          boundedInteger(index, (value.prices as unknown[]).length - 1),
        ) &&
        (row.selection === null || isSelection(row.selection)),
    )
  )
    return false;
  if (value.program === null) return true;
  const program = value.program;
  if (
    !closed(program, ["preferences", "max_total_cost_tenths"]) ||
    !boundedInteger(program.max_total_cost_tenths, 1000) ||
    !Array.isArray(program.preferences) ||
    program.preferences.length < 1 ||
    program.preferences.length > 16
  )
    return false;
  try {
    return program.preferences.every((row) => {
      if (
        !closed(row, ["rules", "priority"]) ||
        (row.priority !== 1 && row.priority !== 2 && row.priority !== 3)
      )
        return false;
      checkedPreferences(row.rules);
      return record(row.rules);
    });
  } catch {
    return false;
  }
}

export function isPriorityResult(value: unknown): value is PriorityResult {
  return (
    closed(value, [
      "contract_version",
      "satisfied",
      "left_out",
      "total_cost",
      "completed_priorities",
      "reference_proved",
      "budget_exhausted",
    ]) &&
    value.contract_version === "llmopt_priority_result_v1" &&
    typeof value.total_cost === "number" &&
    Number.isFinite(value.total_cost) &&
    typeof value.reference_proved === "boolean" &&
    typeof value.budget_exhausted === "boolean" &&
    Array.isArray(value.completed_priorities) &&
    value.completed_priorities.length <= 3 &&
    new Set(value.completed_priorities).size === value.completed_priorities.length &&
    value.completed_priorities.every((level) => level === 1 || level === 2 || level === 3) &&
    [value.satisfied, value.left_out].every(
      (rows) =>
        Array.isArray(rows) &&
        rows.length <= 16 &&
        new Set(rows).size === rows.length &&
        rows.every((identity) => typeof identity === "string"),
    )
  );
}

/** Validate nested advice with the caller's checker; completed components cannot nest bundles. */
export function isPreferenceBundleResult(
  value: unknown,
  validate: (payload: unknown) => boolean,
): boolean {
  if (
    !closed(value, [
      "contract_version",
      "request",
      "components",
      "selected",
      "applied",
      "accepted",
      "budget_exhausted",
    ]) ||
    !isBundle(value.request)
  )
    return false;
  try {
    checkedBundleResult(value, value.request, null, (payload) => {
      if (!validate(payload)) throw new Error("Invalid component advice");
      return payload as EntryAdvice;
    });
    return true;
  } catch {
    return false;
  }
}

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (record(value))
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, sorted(value[key])]),
    );
  return value;
}

export function bundleKey(bundle: PreferenceBundle): string {
  const program = bundle.program && {
    ...bundle.program,
    preferences: bundle.program.preferences
      .map((row) => ({
        rules: checkedPreferences(row.rules),
        priority: row.priority ?? 2,
      }))
      .sort((a, b) => {
        const left = JSON.stringify(sorted(a.rules));
        const right = JSON.stringify(sorted(b.rules));
        return left < right ? -1 : left > right ? 1 : 0;
      }),
  };
  return JSON.stringify(
    sorted({
      ...bundle,
      program,
      choices: [...bundle.choices].sort((a, b) => a.accepted - b.accepted),
    }),
  );
}

export function expandSelection(
  main: DecisionPreferences | undefined,
  selection: PreferenceSelection,
): DecisionPreferences {
  const value: Record<string, unknown> = { ...checkedPreferences(main) };
  for (const [key, item] of Object.entries(selection.preferences)) {
    if (item === null) delete value[key];
    else value[key] = item;
  }
  return checkedPreferences(value);
}

function checkedPriorityResult(value: unknown, program: PriorityProgram): PriorityResult {
  if (!isPriorityResult(value)) throw new Error("Invalid priority outcome");
  const identities: string[] = [];
  for (const rows of [value.satisfied, value.left_out]) {
    if (!Array.isArray(rows) || rows.length > 16) throw new Error("Invalid preference identities");
    for (const identity of rows) {
      if (typeof identity !== "string" || identity.length > 3000)
        throw new Error("Invalid preference identity");
      identities.push(preferencesKey(checkedPreferences(JSON.parse(identity))));
    }
  }
  const expected = program.preferences.map(({ rules }) => preferencesKey(rules));
  if (
    identities.length !== expected.length ||
    new Set(identities).size !== identities.length ||
    expected.some((identity) => !identities.includes(identity))
  )
    throw new Error("Priority outcome names another preference");
  return value as unknown as PriorityResult;
}

/** Response validation is supplied the ordinary advice checker, avoiding another parser. */
export function checkedBundleResult(
  value: unknown,
  request: PreferenceBundle,
  chip: MemberChip | null,
  validate: (payload: unknown, selection: PreferenceSelection) => EntryAdvice,
): PreferenceBundleResult {
  if (
    !record(value) ||
    value.contract_version !== "llmopt_preference_result_v1" ||
    !record(value.request) ||
    !Array.isArray(value.components) ||
    value.components.length !== request.slots.length ||
    typeof value.budget_exhausted !== "boolean" ||
    !Number.isInteger(value.accepted) ||
    (value.accepted as number) < 0 ||
    (value.accepted as number) > 65535 ||
    !Array.isArray(value.applied) ||
    value.applied.length > 16 ||
    value.applied.some(
      (index) => !Number.isInteger(index) || index < 0 || index >= request.prices.length,
    ) ||
    new Set(value.applied).size !== value.applied.length
  )
    throw new Error("Invalid preference result");
  if (bundleKey(value.request as unknown as PreferenceBundle) !== bundleKey(request))
    throw new Error("Preference result answers another request");
  function component(raw: unknown, selection: PreferenceSelection | null): PreferenceComponent {
    if (
      !record(raw) ||
      Object.keys(raw).some(
        (key) => !["status", "payload", "error_code", "infeasibility"].includes(key),
      ) ||
      !["done", "failed", "exhausted", "unavailable"].includes(String(raw.status)) ||
      (raw.error_code !== null &&
        (typeof raw.error_code !== "string" || !/^[A-Z][A-Z0-9_]{0,63}$/.test(raw.error_code)))
    )
      throw new Error("Invalid preference component");
    if (raw.status === "done") {
      if (
        !selection ||
        !record(raw.payload) ||
        raw.payload.preference_bundle_result !== undefined ||
        raw.error_code !== null
      )
        throw new Error("Invalid completed preference component");
      return { status: "done", payload: validate(raw.payload, selection), error_code: null };
    }
    if (raw.payload !== null || raw.error_code === null)
      throw new Error("Invalid incomplete preference component");
    const infeasibility =
      raw.infeasibility === undefined ? undefined : checkedPlanInfeasibility(raw.infeasibility);
    if (raw.infeasibility !== undefined && !infeasibility)
      throw new Error("Invalid component diagnosis");
    return {
      ...raw,
      ...(infeasibility ? { infeasibility } : {}),
    } as unknown as PreferenceComponent;
  }
  const choice = request.choices.find(({ accepted }) => accepted === value.accepted);
  const selection = request.program ? { preferences: {}, chip } : (choice?.selection ?? null);
  const selected = value.selected === null ? null : component(value.selected, selection);
  if (request.program && selected?.status === "done" && selected.payload) {
    selected.payload.priority_preferences = checkedPriorityResult(
      selected.payload.priority_preferences,
      request.program,
    );
  }
  if (request.program === null && request.choices.length && !choice)
    throw new Error("Unknown preference combination");
  if (
    selected?.status === "done" &&
    !request.program &&
    JSON.stringify(value.applied) !== JSON.stringify(choice?.applied)
  )
    throw new Error("Wrong applied preferences");
  return {
    contract_version: "llmopt_preference_result_v1",
    request,
    components: value.components.map((row, index) => component(row, request.slots[index] ?? null)),
    selected,
    applied: value.applied as number[],
    accepted: value.accepted as number,
    budget_exhausted: value.budget_exhausted,
  };
}
