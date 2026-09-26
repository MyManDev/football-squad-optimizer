import { checkedPreferences, preferencesKey } from "./decisionPreferences";
import { LeagueDataError } from "../dataErrors";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import type { AdviceRequest } from "./adviceClient";
import { isAdvicePayload } from "./adviceShape";

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
    !isAdvicePayload(payload) ||
    typeof value.generated_at_utc !== "string" ||
    !value.generated_at_utc.endsWith("Z") ||
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
  // A request that states its switches is answered only by the plan solved under them: a
  // weighted document names its weight and the plain one names none, and the plan with the
  // manager's word carries its evidence and the plain one does not. A request that states
  // neither (every request of a static build) is held to nothing here, as before.
  const identity = payload.prediction_model;
  const model = record(identity) ? identity.id : "current";
  if (model !== (request.model ?? "current"))
    throw new AdviceContextError("Advice uses another prediction model.");
  try {
    const actual = preferencesKey(checkedPreferences(payload.preferences));
    if (
      actual !== preferencesKey(request.preferences) ||
      (actual && payload.preferences_scope !== "all_selected_weeks")
    )
      throw new Error("Preference mismatch");
  } catch {
    throw new AdviceContextError("Advice does not match the selected preferences.");
  }
  const top100 = payload.top100;
  const strategy = record(payload.chip_strategy) ? payload.chip_strategy : null;
  const chosenChip =
    strategy?.requested_chip ?? (record(payload.chip_choice) ? payload.chip_choice.chip : null);
  const selectedChip = strategy ? strategy.selected_chip : chosenChip;
  if (
    (request.top100Weight !== undefined &&
      (strategy?.top100_weight ??
        payload.selection_top100_weight ??
        (record(top100) ? top100.weight : 0) ??
        0) !== request.top100Weight) ||
    (request.managersWord !== undefined &&
      (payload.evidence !== undefined) !== request.managersWord) ||
    (request.chip !== undefined &&
      (chosenChip !== request.chip || (payload.chip ?? null) !== selectedChip))
  ) {
    throw new AdviceContextError("Advice does not match the selected switches.");
  }
  return value as unknown as LeagueViewEnvelope<EntryAdvice>;
}
