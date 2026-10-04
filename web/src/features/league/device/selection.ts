/**
 * Which selections the device can solve from the published inputs, and what each one
 * needs: the plain pure-points plan over one week; the same with a chip the member still
 * holds; a rival strategy over one week against a named rival. Nothing switched on
 * beyond that (the club's word, a Top 100 weight, the football model, preferences, a
 * longer window) is the service's.
 */

import type { AdviceRequest } from "../advice/adviceClient";
import type { EntrySquad, EntrySquadPlayer } from "../types";
import {
  isDeviceChip,
  isRivalStrategy,
  type DeviceChip,
  type DeviceRival,
  type RivalStrategy,
} from "./types";

export type DeviceSelection =
  | { kind: "plain" }
  | { kind: "chip"; chip: DeviceChip }
  | { kind: "rival"; strategy: RivalStrategy; rivalEntryId: number };

/**
 * The chip the request asks to play, if it is one the device can solve: a chip the squad
 * document says the member can still play this gameweek, as the server reads the
 * member's chip menu (a half still available whose window holds the decided gameweek).
 * Null for no chip; undefined for a chip the device cannot take.
 */
export function deviceChip(
  request: Pick<AdviceRequest, "chip">,
  squad: Pick<EntrySquad, "chips">,
): DeviceChip | null | undefined {
  const chip = request.chip ?? null;
  if (chip === null) return null;
  if (!isDeviceChip(chip) || !squad.chips?.known) return undefined;
  const halves = squad.chips.states[chip];
  const gameweek = squad.chips.gameweek;
  const playable =
    halves !== undefined &&
    Object.values(halves).some(
      (half) =>
        half !== null &&
        half.state === "available" &&
        half.start_event <= gameweek &&
        gameweek <= half.stop_event,
    );
  return playable ? chip : undefined;
}

/** The selection the device would solve for this request, or null where it is the service's. */
export function deviceSelection(
  request: AdviceRequest,
  squad: Pick<EntrySquad, "chips">,
): DeviceSelection | null {
  if (
    request.window !== 1 ||
    (request.top100Weight ?? 0) !== 0 ||
    (request.managersWord ?? false) ||
    (request.model ?? "current") !== "current" ||
    request.preferences
  ) {
    return null;
  }
  const chip = deviceChip(request, squad);
  if (chip === undefined) return null;
  const rivalEntryId = request.rivalEntryId ?? null;
  if (request.strategy === "saf-puan") {
    if (rivalEntryId !== null) return null;
    return chip === null ? { kind: "plain" } : { kind: "chip", chip };
  }
  // A rival strategy combines with no chip, as on the server.
  if (!isRivalStrategy(request.strategy) || rivalEntryId === null || chip !== null) return null;
  return { kind: "rival", strategy: request.strategy, rivalEntryId };
}

/** The rival as the device needs them, from their entry document; null when it names no captain. */
export function rivalFromSquad(
  entryId: number,
  squad: Pick<EntrySquad, "starting_xi">,
): DeviceRival | null {
  const captain = squad.starting_xi.find((player: EntrySquadPlayer) => player.is_captain);
  if (!captain) return null;
  return {
    entry_id: entryId,
    starting_xi: squad.starting_xi.map((player) => player.player_id),
    captain: captain.player_id,
  };
}
