import type { AdviceChip, EntrySquad } from "../types";

export interface ForecastChip {
  name: AdviceChip;
  window: { first_gameweek: number; last_gameweek: number };
  holding_value: number;
  verdict: "play_now" | "hold" | "unknown_this_week";
  hold_reason: "gain_not_above_threshold" | "reserved_for_structured_gameweek" | null;
  gain_this_week: number | null;
  threshold_this_week: number;
  reservation_allows_this_week: boolean;
  points_at_gameweek: {
    gameweek: number;
    estimated_gain: number;
    threshold: number;
    player_ids: number[];
  } | null;
  structured_gameweeks:
    | {
        gameweek: number;
        clubs_doubling: number;
        clubs_blank: number;
      }[]
    | null;
}
export interface ForecastDocument {
  contract_version: "chip_forecast_v1";
  decision_gameweek: number;
  threshold_policy: "decaying" | "fixed";
  reserve: boolean;
  later_week_basis: "this_week_projection_scaled_by_relative_fixture_count_v1";
  players_without_fixture_this_week: number[];
  chips: ForecastChip[];
  limits: string[];
}
export type ForecastReading =
  | { kind: "absent" }
  | { kind: "refused"; reason: string }
  | {
      kind: "ready";
      document: ForecastDocument;
      calendarHasStructure: boolean;
      calendarRange: { first_gameweek: number; last_gameweek: number } | null;
    };

const object = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const number = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const integer = (v: unknown): v is number => number(v) && Number.isSafeInteger(v) && v >= 0;
const ids = (v: unknown): v is number[] =>
  Array.isArray(v) && v.every((n) => integer(n) && n > 0) && new Set(v).size === v.length;
const keys = (v: Record<string, unknown>, names: string[]) =>
  Object.keys(v).length === names.length && names.every((name) => name in v);
const same = (a: number[], b: number[]) => a.length === b.length && a.every((n) => b.includes(n));
const chips = ["wildcard", "freehit", "bboost", "3xc"];

/** Invalid or stale optional evidence never invalidates the member's existing plan. */
export function readChipForecast(value: unknown, squad: EntrySquad): ForecastReading {
  if (value === undefined) return { kind: "absent" };
  const refused = (reason = "forecast_unreadable"): ForecastReading => ({
    kind: "refused",
    reason,
  });
  if (
    !object(value) ||
    !keys(value, [
      "season",
      "league_id",
      "entry_id",
      "gameweek",
      "source_snapshot_id",
      "squad_player_ids",
      "bench_player_ids",
      "status",
      "reason",
      "forecast",
      "calendar_has_structure",
      "calendar_range",
    ])
  )
    return refused();
  const squadIds = [...squad.starting_xi, ...squad.bench].map((p) => p.player_id);
  const benchIds = squad.bench.map((p) => p.player_id);
  if (
    value.season !== squad.season ||
    value.league_id !== squad.league_id ||
    value.entry_id !== squad.entry.entry_id ||
    value.gameweek !== squad.gameweek ||
    typeof value.source_snapshot_id !== "string" ||
    !value.source_snapshot_id ||
    value.source_snapshot_id !== squad.source_snapshot_id ||
    !ids(value.squad_player_ids) ||
    value.squad_player_ids.length !== 15 ||
    !same(value.squad_player_ids, squadIds) ||
    !ids(value.bench_player_ids) ||
    value.bench_player_ids.length !== 4 ||
    !same(value.bench_player_ids, benchIds)
  )
    return refused("capture_mismatch");
  if (value.status === "unavailable")
    return value.forecast === null &&
      typeof value.reason === "string" &&
      value.calendar_has_structure === null &&
      value.calendar_range === null
      ? refused(value.reason)
      : refused();
  if (value.status !== "available" || value.reason !== null) return refused();
  const doc = value.forecast;
  if (
    !object(doc) ||
    !keys(doc, [
      "contract_version",
      "decision_gameweek",
      "threshold_policy",
      "reserve",
      "later_week_basis",
      "players_without_fixture_this_week",
      "chips",
      "limits",
    ]) ||
    doc.contract_version !== "chip_forecast_v1" ||
    doc.decision_gameweek !== squad.gameweek ||
    !["decaying", "fixed"].includes(String(doc.threshold_policy)) ||
    typeof doc.reserve !== "boolean" ||
    doc.later_week_basis !== "this_week_projection_scaled_by_relative_fixture_count_v1" ||
    !ids(doc.players_without_fixture_this_week) ||
    !doc.players_without_fixture_this_week.every((id) => squadIds.includes(id)) ||
    !Array.isArray(doc.chips) ||
    doc.chips.length > 4 ||
    !Array.isArray(doc.limits) ||
    doc.limits.length === 0 ||
    !doc.limits.every((line) => typeof line === "string" && line.length > 0) ||
    new Set(doc.limits).size !== doc.limits.length
  )
    return refused();
  const idle = doc.players_without_fixture_this_week;
  const names = new Set<string>();
  for (const row of doc.chips) {
    if (
      !object(row) ||
      !keys(row, [
        "name",
        "window",
        "holding_value",
        "verdict",
        "hold_reason",
        "gain_this_week",
        "threshold_this_week",
        "reservation_allows_this_week",
        "points_at_gameweek",
        "structured_gameweeks",
      ]) ||
      typeof row.name !== "string" ||
      !chips.includes(row.name) ||
      names.has(row.name) ||
      !object(row.window) ||
      !keys(row.window, ["first_gameweek", "last_gameweek"]) ||
      !integer(row.window.first_gameweek) ||
      row.window.first_gameweek < 1 ||
      !integer(row.window.last_gameweek) ||
      row.window.first_gameweek > squad.gameweek ||
      row.window.last_gameweek < squad.gameweek ||
      !number(row.holding_value) ||
      row.holding_value < 0 ||
      !number(row.threshold_this_week) ||
      row.threshold_this_week < 0 ||
      typeof row.reservation_allows_this_week !== "boolean" ||
      (row.gain_this_week !== null && !number(row.gain_this_week))
    )
      return refused();
    names.add(row.name);
    const windows = squad.chips?.states[row.name];
    if (
      !squad.chips?.known ||
      !windows ||
      !Object.values(windows).some(
        (w) =>
          w?.state === "available" &&
          w.start_event === (row.window as Record<string, unknown>).first_gameweek &&
          w.stop_event === (row.window as Record<string, unknown>).last_gameweek,
      )
    )
      return refused("capture_mismatch");
    if (row.verdict === "unknown_this_week") {
      if (
        row.gain_this_week !== null ||
        row.hold_reason !== null ||
        !row.reservation_allows_this_week
      )
        return refused();
    } else if (row.verdict === "play_now") {
      if (
        !number(row.gain_this_week) ||
        row.gain_this_week <= row.threshold_this_week ||
        row.hold_reason !== null ||
        row.points_at_gameweek !== null ||
        !row.reservation_allows_this_week
      )
        return refused();
    } else if (row.verdict === "hold") {
      if (row.hold_reason === "gain_not_above_threshold") {
        if (
          !number(row.gain_this_week) ||
          row.gain_this_week > row.threshold_this_week ||
          !row.reservation_allows_this_week
        )
          return refused();
      } else if (
        row.hold_reason !== "reserved_for_structured_gameweek" ||
        row.reservation_allows_this_week ||
        !doc.reserve
      )
        return refused();
    } else return refused();
    const later = row.points_at_gameweek;
    if (later !== null) {
      if (
        !["bboost", "3xc"].includes(row.name) ||
        !object(later) ||
        !keys(later, ["gameweek", "estimated_gain", "threshold", "player_ids"]) ||
        !integer(later.gameweek) ||
        later.gameweek <= squad.gameweek ||
        later.gameweek > row.window.last_gameweek ||
        !number(later.estimated_gain) ||
        !number(later.threshold) ||
        later.threshold < 0 ||
        later.estimated_gain <= later.threshold ||
        !ids(later.player_ids) ||
        later.player_ids.length === 0 ||
        !later.player_ids.every(
          (id) => (row.name === "bboost" ? benchIds : squadIds).includes(id) && !idle.includes(id),
        ) ||
        (row.name === "3xc" && later.player_ids.length !== 1)
      )
        return refused();
    }
    if (row.name === "freehit") {
      if (!Array.isArray(row.structured_gameweeks)) return refused();
      let previous = squad.gameweek;
      for (const week of row.structured_gameweeks) {
        if (
          !object(week) ||
          !keys(week, ["gameweek", "clubs_doubling", "clubs_blank"]) ||
          !integer(week.gameweek) ||
          week.gameweek <= previous ||
          week.gameweek > row.window.last_gameweek ||
          !integer(week.clubs_doubling) ||
          !integer(week.clubs_blank) ||
          week.clubs_doubling + week.clubs_blank === 0
        )
          return refused();
        previous = week.gameweek;
      }
    } else if (row.structured_gameweeks !== null) return refused();
  }
  const available = Object.entries(squad.chips?.states ?? {})
    .filter(([, halves]) =>
      Object.values(halves).some(
        (w) =>
          w?.state === "available" &&
          w.start_event <= squad.gameweek &&
          w.stop_event >= squad.gameweek,
      ),
    )
    .map(([name]) => name);
  if (available.length !== names.size || available.some((name) => !names.has(name)))
    return refused();
  if (typeof value.calendar_has_structure !== "boolean") return refused();
  const last = Math.max(squad.gameweek, ...doc.chips.map((row) => row.window.last_gameweek));
  const range = value.calendar_range;
  if (last === squad.gameweek) {
    if (range !== null || value.calendar_has_structure !== false) return refused();
  } else if (
    !object(range) ||
    !keys(range, ["first_gameweek", "last_gameweek"]) ||
    range.first_gameweek !== squad.gameweek + 1 ||
    range.last_gameweek !== last
  )
    return refused();
  return {
    kind: "ready",
    document: doc as unknown as ForecastDocument,
    calendarHasStructure: value.calendar_has_structure,
    calendarRange: range as { first_gameweek: number; last_gameweek: number } | null,
  };
}
