import { checkedPreferences, preferenceScope, preferencesKey } from "./decisionPreferences";
import { LeagueDataError } from "../dataErrors";
import type { AdvicePlayer, EntryAdvice, LeagueViewEnvelope } from "../types";
import type { AdviceRequest } from "./adviceClient";
import { isAdvicePayload } from "./adviceShape";
import { checkedBundleResult, expandSelection } from "./preferenceBundle";

export class AdviceResponseError extends LeagueDataError {}

export class AdviceContextError extends AdviceResponseError {}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function samePlayers(players: AdvicePlayer[], expected: number[]) {
  const ids = new Set(players.map(({ player_id }) => player_id));
  return players.length === expected.length && expected.every((id) => ids.has(id));
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
      (actual && payload.preferences_scope !== preferenceScope(request.preferences))
    )
      throw new Error("Preference mismatch");
  } catch {
    throw new AdviceContextError("Advice does not match the selected preferences.");
  }
  const requested = request.preferences;
  const plan = payload as unknown as EntryAdvice;
  if (requested?.scenario?.kind === "unavailable") {
    const { player_id, week = 1 } = requested.scenario;
    const lineup = plan.plan_weeks?.find(
      (row) => row.gameweek === plan.gameweek + week - 1,
    )?.lineup;
    if (
      !lineup ||
      lineup.captain.player_id === player_id ||
      lineup.vice_captain.player_id === player_id ||
      lineup.starting_xi.some((player) => player.player_id === player_id)
    )
      throw new AdviceContextError("Advice starts or captains the scenario's unavailable player.");
  }
  for (const frozen of requested?.frozen_weeks ?? []) {
    const week = plan.plan_weeks?.find((row) => row.gameweek === plan.gameweek + frozen.week - 1);
    if (
      !week ||
      week.chip !== frozen.chip ||
      !samePlayers(week.transfers_in, frozen.transfers_in) ||
      !samePlayers(week.transfers_out, frozen.transfers_out) ||
      (frozen.starting_xi &&
        (!week.lineup ||
          week.lineup.captain.player_id !== frozen.captain ||
          !samePlayers(week.lineup.starting_xi, frozen.starting_xi)))
    )
      throw new AdviceContextError("Advice changes a frozen week.");
  }
  if (requested?.min_bank) {
    const { tenths, week = request.window } = requested.min_bank;
    const carried = plan.plan_weeks?.find(
      (row) => row.gameweek === plan.gameweek + week - 1,
    )?.bank_after_tenths;
    if (carried === undefined || carried < tenths)
      throw new AdviceContextError("Advice does not retain the required budget.");
  }
  if (requested?.hold_opening_transfers) {
    const opening = plan.plan_weeks?.find((week) => week.gameweek === plan.gameweek);
    const openingChip = opening ? opening.chip : plan.chip;
    if (
      plan.moves.some((move) => move.player_in != null || move.player_out != null) ||
      opening?.transfers_in.length ||
      opening?.transfers_out.length ||
      (opening?.transfer_hit_points ?? plan.transfer_hit_points ?? 0) !== 0 ||
      openingChip === "wildcard" ||
      openingChip === "freehit"
    ) {
      throw new AdviceContextError("Advice does not hold transfers in the selected week.");
    }
  }
  if (
    requested?.min_opening_bank_tenths !== undefined &&
    (plan.bank_after_tenths === undefined ||
      plan.bank_after_tenths < requested.min_opening_bank_tenths)
  ) {
    throw new AdviceContextError("Advice does not retain the required opening budget.");
  }
  if (request.preferences?.wildcard_week !== undefined) {
    const gameweek =
      typeof payload.gameweek === "number"
        ? payload.gameweek + request.preferences.wildcard_week - 1
        : null;
    if (
      !Array.isArray(payload.plan_weeks) ||
      !payload.plan_weeks.some(
        (week) => record(week) && week.gameweek === gameweek && week.chip === "wildcard",
      )
    )
      throw new AdviceContextError("Advice does not play the Wildcard in the selected week.");
  }
  const top100 = payload.top100;
  const strategy = record(payload.chip_strategy) ? payload.chip_strategy : null;
  const chosenChip =
    strategy?.requested_chip ?? (record(payload.chip_choice) ? payload.chip_choice.chip : null);
  const selectedChip = strategy ? strategy.selected_chip : chosenChip;
  const requestedChip =
    request.preferences?.wildcard_week === undefined ? request.chip : "wildcard";
  if (
    (request.top100Weight !== undefined &&
      (strategy?.top100_weight ??
        payload.selection_top100_weight ??
        (record(top100) ? top100.weight : 0) ??
        0) !== request.top100Weight) ||
    (request.managersWord !== undefined &&
      (payload.evidence !== undefined) !== request.managersWord) ||
    (requestedChip !== undefined &&
      (chosenChip !== requestedChip || (payload.chip ?? null) !== selectedChip))
  ) {
    throw new AdviceContextError("Advice does not match the selected switches.");
  }
  if (request.preferenceBundle) {
    try {
      const child = { ...request };
      delete child.preferenceBundle;
      payload.preference_bundle_result = checkedBundleResult(
        payload.preference_bundle_result,
        request.preferenceBundle,
        request.chip === "auto" ? null : (request.chip ?? null),
        (computed, selection) =>
          checkedAdvice(
            { ...value, payload: computed },
            {
              ...child,
              preferences: expandSelection(request.preferences, selection),
              chip: selection.chip,
            },
          ).payload,
      );
    } catch {
      throw new AdviceContextError("Advice does not match its preference execution.");
    }
  }
  return value as unknown as LeagueViewEnvelope<EntryAdvice>;
}
