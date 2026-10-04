/**
 * What the device can compute for a member, stated the way the service's capabilities
 * are: the strategies, the windows and the rivals. The page's controls offer a selection
 * from any of its three sources (the publish, the service, the device); this is the
 * device's statement, made from the member's published inputs and the league's members.
 */

import { rivalCandidates } from "../advice/adviceSelection";
import type { EntrySquad, EntryView } from "../types";
import { isDevicePlanEntry, RIVAL_STRATEGIES } from "./types";

export interface DeviceComputable {
  strategies: Array<"saf-puan" | (typeof RIVAL_STRATEGIES)[number]>;
  windows: 1[];
  rivals: number[];
}

/** The device's statement for this member, or undefined where the publish wrote no inputs. */
export function deviceComputable(
  squad: Pick<EntrySquad, "device_plan" | "source_snapshot_id" | "entry">,
  members: EntryView[],
): DeviceComputable | undefined {
  if (!isDevicePlanEntry(squad.device_plan) || squad.source_snapshot_id === null) return undefined;
  return {
    strategies: ["saf-puan", ...RIVAL_STRATEGIES],
    windows: [1],
    rivals: rivalCandidates(members, squad.entry.entry_id)
      .map((member) => member.entry_id)
      .filter((id): id is number => typeof id === "number"),
  };
}
