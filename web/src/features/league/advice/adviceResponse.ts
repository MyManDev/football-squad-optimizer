import { LeagueDataError } from "../data";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import type { AdviceRequest } from "./adviceClient";

export class AdviceResponseError extends LeagueDataError {}

export class AdviceContextError extends AdviceResponseError {}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** A successful transport response still has to answer the selected member and week. */
export function checkedAdvice(
  value: unknown,
  request: AdviceRequest,
): LeagueViewEnvelope<EntryAdvice> {
  if (!record(value) || value.contract_version !== "provisional_league_ui_v1") {
    throw new AdviceResponseError("Invalid advice envelope.");
  }
  const payload = value.payload;
  if (
    !record(payload) ||
    !Array.isArray(payload.moves) ||
    typeof value.generated_at_utc !== "string" ||
    (value.source_kind !== "live" && value.source_kind !== "example") ||
    typeof payload.league_id !== "number" ||
    typeof payload.entry_id !== "number" ||
    typeof payload.mode !== "string" ||
    typeof payload.window !== "number" ||
    (request.season !== undefined && typeof payload.season !== "string") ||
    (request.gameweek !== undefined && typeof payload.gameweek !== "number") ||
    (request.rivalEntryId != null && typeof payload.rival_entry_id !== "number")
  ) {
    throw new AdviceResponseError("Invalid advice payload.");
  }
  if (
    payload.league_id !== request.leagueId ||
    payload.entry_id !== request.entryId ||
    payload.mode !== request.strategy ||
    payload.window !== request.window ||
    (request.season !== undefined && payload.season !== request.season) ||
    (request.gameweek !== undefined && payload.gameweek !== request.gameweek) ||
    (request.rivalEntryId != null && payload.rival_entry_id !== request.rivalEntryId)
  ) {
    throw new AdviceContextError("Advice does not match the selected member, strategy or week.");
  }
  return value as unknown as LeagueViewEnvelope<EntryAdvice>;
}
