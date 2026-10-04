/**
 * What the device can compute for a member, stated the way the service's capabilities
 * are: the strategies, the windows and the rivals. The page's controls offer a selection
 * from any of its three sources (the publish, the service, the device); this is the
 * device's statement, made from the member's published inputs, the league's members and
 * the rivals' own entry documents.
 */

import { rivalCandidates, type DeviceComputable } from "../advice/adviceSelection";
import { isTop100Weight } from "../advice/top100";
import type { EntrySquad, EntryView } from "../types";
import { rivalFromSquad } from "./selection";
import { isDevicePlanEntry, RIVAL_STRATEGIES } from "./types";

export type { DeviceComputable } from "../advice/adviceSelection";

/**
 * Whether the device can play a rival strategy against this rival: their entry document is
 * on the member's capture and names a captain in their eleven. The device solves against
 * that eleven and that captain, and refuses a rival without them, as the server does.
 */
export function deviceRivalUsable(
  squad: Pick<EntrySquad, "source_snapshot_id">,
  rival: Pick<EntrySquad, "entry" | "source_snapshot_id" | "starting_xi">,
): boolean {
  return (
    squad.source_snapshot_id !== null &&
    rival.source_snapshot_id === squad.source_snapshot_id &&
    rivalFromSquad(rival.entry.entry_id, rival) !== null
  );
}

/**
 * The device's statement for this member, or undefined where the publish wrote no inputs.
 * A rival is in it only once their entry document has been read and the device can use it,
 * so the member is never offered a rival the device would refuse.
 */
export function deviceComputable(
  squad: Pick<EntrySquad, "device_plan" | "source_snapshot_id" | "entry">,
  members: EntryView[],
  rivalSquads: readonly Pick<EntrySquad, "entry" | "source_snapshot_id" | "starting_xi">[],
): DeviceComputable | undefined {
  if (!isDevicePlanEntry(squad.device_plan) || squad.source_snapshot_id === null) return undefined;
  const usable = (id: number) =>
    rivalSquads.some((rival) => rival.entry.entry_id === id && deviceRivalUsable(squad, rival));
  return {
    strategies: ["saf-puan", ...RIVAL_STRATEGIES],
    windows: [1],
    rivals: rivalCandidates(members, squad.entry.entry_id)
      .map((member) => member.entry_id)
      .filter((id): id is number => typeof id === "number" && usable(id)),
    top100Weights: [0, ...(squad.device_plan.top100_weights ?? []).filter(isTop100Weight)],
  };
}
