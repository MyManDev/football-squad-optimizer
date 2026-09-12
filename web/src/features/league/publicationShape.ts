import { LeagueDataError } from "./dataErrors";
import type { EntryAdviceIndex, EntrySquad, LeagueMembers, LeagueViewEnvelope } from "./types";

const CONTRACT_VERSION = "provisional_league_ui_v1";

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function nullableNumber(value: unknown): boolean {
  return value === null || finite(value);
}

function publicMember(value: unknown): boolean {
  if (!record(value)) return false;
  return (
    ((value.member_kind === "human" &&
      Number.isSafeInteger(value.entry_id) &&
      Number(value.entry_id) > 0) ||
      (value.member_kind === "system" && value.entry_id === null)) &&
    (value.manager_name === null || typeof value.manager_name === "string") &&
    (value.team_name === null || typeof value.team_name === "string") &&
    finite(value.rank) &&
    nullableNumber(value.gameweek_points) &&
    nullableNumber(value.total_points) &&
    (value.transfer_cost === undefined || nullableNumber(value.transfer_cost)) &&
    typeof value.movement === "string" &&
    ["up", "down", "same", "new", "unknown"].includes(value.movement) &&
    (value.movement_places === undefined || nullableNumber(value.movement_places))
  );
}

function publishedPlayer(value: unknown): boolean {
  return (
    record(value) &&
    Number.isSafeInteger(value.player_id) &&
    Number(value.player_id) > 0 &&
    typeof value.name === "string" &&
    typeof value.short_name === "string" &&
    typeof value.team === "string" &&
    typeof value.position === "string" &&
    ["GK", "DEF", "MID", "FWD"].includes(value.position) &&
    finite(value.expected_points) &&
    typeof value.is_captain === "boolean" &&
    (value.bench_order == null || Number.isSafeInteger(value.bench_order))
  );
}

const CHIP_WINDOW_STATES = ["used", "expired", "not_yet", "available", "unknown"];
const CHIP_HALVES = ["first_half", "second_half"];

function chipWindow(value: unknown): boolean {
  return (
    value === null ||
    (record(value) &&
      typeof value.state === "string" &&
      CHIP_WINDOW_STATES.includes(value.state) &&
      nullableNumber(value.gameweek) &&
      Number.isSafeInteger(value.start_event) &&
      Number.isSafeInteger(value.stop_event))
  );
}

/** The `chips` block: a flag, the gameweek it was read before, and every chip by half. */
function chipAvailability(value: unknown): boolean {
  return (
    record(value) &&
    typeof value.known === "boolean" &&
    Number.isSafeInteger(value.gameweek) &&
    record(value.states) &&
    Object.values(value.states).every(
      (halves) =>
        record(halves) &&
        Object.keys(halves).every((half) => CHIP_HALVES.includes(half)) &&
        CHIP_HALVES.every((half) => half in halves && chipWindow(halves[half])),
    )
  );
}

export function assertEnvelope<T>(value: unknown): LeagueViewEnvelope<T> {
  if (
    !record(value) ||
    value.contract_version !== CONTRACT_VERSION ||
    !record(value.payload) ||
    typeof value.generated_at_utc !== "string" ||
    (value.source_kind !== "live" && value.source_kind !== "example")
  ) {
    throw new LeagueDataError("The published league envelope is invalid.");
  }
  return value as unknown as LeagueViewEnvelope<T>;
}

export function assertMembers(
  envelope: LeagueViewEnvelope<LeagueMembers>,
): LeagueViewEnvelope<LeagueMembers> {
  const view = envelope.payload;
  if (
    !record(view) ||
    !Number.isSafeInteger(view.league_id) ||
    view.league_id <= 0 ||
    typeof view.league_name !== "string" ||
    typeof view.season !== "string" ||
    !Number.isSafeInteger(view.gameweek) ||
    view.public_after_deadline !== true ||
    (view.scored_gameweek !== null && !Number.isSafeInteger(view.scored_gameweek)) ||
    !Array.isArray(view.members) ||
    !view.members.every(publicMember)
  ) {
    throw new LeagueDataError("The published member list is invalid.");
  }
  return envelope;
}

export function assertSquad(
  envelope: LeagueViewEnvelope<EntrySquad>,
  entryId: number,
): LeagueViewEnvelope<EntrySquad> {
  const view = envelope.payload;
  if (
    !record(view) ||
    !publicMember(view.entry) ||
    view.entry.member_kind !== "human" ||
    view.entry.entry_id !== entryId ||
    !Number.isSafeInteger(view.league_id) ||
    view.league_id <= 0 ||
    typeof view.season !== "string" ||
    !Number.isSafeInteger(view.gameweek) ||
    (view.source_snapshot_id !== null && typeof view.source_snapshot_id !== "string") ||
    !Array.isArray(view.starting_xi) ||
    !view.starting_xi.every(publishedPlayer) ||
    !Array.isArray(view.bench) ||
    !view.bench.every(publishedPlayer) ||
    !Array.isArray(view.missing_fields) ||
    !view.missing_fields.every((field) => typeof field === "string") ||
    !["complete", "partial", "empty"].includes(view.data_quality) ||
    typeof view.free_transfers_known !== "boolean" ||
    typeof view.purchase_prices_known !== "boolean" ||
    !finite(view.free_transfers) ||
    // The state fields are optional (documents from before them carry none) but never
    // malformed: a wrong shape is refused like every other field, not read as absent.
    (view.chips !== undefined && !chipAvailability(view.chips)) ||
    (view.squad_basis !== undefined &&
      (typeof view.squad_basis !== "string" || view.squad_basis.trim() === "")) ||
    (view.active_chip !== undefined &&
      view.active_chip !== null &&
      (typeof view.active_chip !== "string" || view.active_chip.trim() === ""))
  ) {
    throw new LeagueDataError("The published member squad is invalid or belongs to another entry.");
  }
  return envelope;
}

export function assertAdviceIndex(
  envelope: LeagueViewEnvelope<EntryAdviceIndex>,
  entryId: number,
): LeagueViewEnvelope<EntryAdviceIndex> {
  const index = envelope.payload;
  const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
  const window = (value: unknown) => [1, 3, 5].includes(Number(value)) && typeof value === "number";
  if (
    !record(index) ||
    index.entry_id !== entryId ||
    !positive(index.league_id) ||
    !positive(index.gameweek) ||
    typeof index.season !== "string" ||
    !window(index.window) ||
    !Array.isArray(index.strategies) ||
    !index.strategies.every((item) => typeof item === "string") ||
    !Array.isArray(index.rival_entry_ids) ||
    !index.rival_entry_ids.every(positive) ||
    !(index.default_rival_entry_id === null || positive(index.default_rival_entry_id)) ||
    !Array.isArray(index.computed) ||
    !index.computed.every(
      (item) =>
        record(item) &&
        typeof item.strategy === "string" &&
        positive(item.rival_entry_id) &&
        item.path === `advice/${entryId}/${item.strategy}/1/vs-${item.rival_entry_id}.json`,
    ) ||
    !Array.isArray(index.unavailable) ||
    !index.unavailable.every(
      (item) =>
        record(item) &&
        typeof item.strategy === "string" &&
        typeof item.reason === "string" &&
        (item.rival_entry_id === null || positive(item.rival_entry_id)) &&
        (item.window === undefined || window(item.window)),
    ) ||
    (index.windows !== undefined &&
      (!record(index.windows) ||
        !Object.values(index.windows).every(
          (items) => Array.isArray(items) && items.every(window),
        )))
  ) {
    throw new LeagueDataError("The published advice index is invalid or belongs to another entry.");
  }
  const suggestion = index.suggested_strategy;
  if (
    suggestion != null &&
    (!record(suggestion) ||
      !["saf-puan", "ortak-koru", "fark-yarat"].includes(String(suggestion.strategy)) ||
      typeof suggestion.rule_id !== "string" ||
      !["behind", "level", "ahead"].includes(String(suggestion.band)) ||
      !positive(suggestion.rival_entry_id) ||
      !finite(suggestion.points_ahead_of_rival) ||
      !positive(suggestion.scored_gameweek) ||
      !finite(suggestion.gameweeks_remaining) ||
      !finite(suggestion.band_edge_points))
  ) {
    throw new LeagueDataError("The published strategy suggestion is invalid.");
  }
  return envelope;
}
