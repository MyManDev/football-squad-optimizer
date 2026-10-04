/**
 * The member page's one resolver: which advice a link selects, with the device's statement
 * beside the publish and the service. The page's reads (`useLeagueMemberData`) and its view
 * (`useMemberAdviceView`) both resolve through here from the same inputs, so the rival the
 * device solves against is the rival whose squad the page reads, and never one resolved
 * without the device in one place and with it in the other.
 */

import type { AdviceCapabilities } from "../advice/adviceCapabilities";
import type { AdviceRequest } from "../advice/adviceClient";
import {
  resolvePublishedAdvice,
  type DeviceComputable,
  type PublishedAdviceSelection,
} from "../advice/adviceSelection";
import { deviceComputable, type DeviceRivalReads } from "../device/computable";
import type { EntryAdviceIndex, EntrySquad, EntryView } from "../types";

export interface MemberSelectionInputs {
  squad: EntrySquad;
  members: EntryView[];
  index: EntryAdviceIndex | null;
  capabilities: AdviceCapabilities | null;
  /** What the page has read of the rivals' entry documents; the device's statement is made from it. */
  deviceRivals: DeviceRivalReads;
}

export interface MemberSelection {
  onDevice: DeviceComputable | undefined;
  resolve: (params: URLSearchParams) => PublishedAdviceSelection;
}

export function memberSelection({
  squad,
  members,
  index,
  capabilities,
  deviceRivals,
}: MemberSelectionInputs): MemberSelection {
  const onDevice = deviceComputable(squad, members, deviceRivals);
  const resolve = (params: URLSearchParams) =>
    resolvePublishedAdvice(
      params,
      squad.league_id,
      squad.entry.entry_id,
      members,
      index,
      { season: squad.season, gameweek: squad.gameweek },
      capabilities,
      onDevice,
    );
  return { onDevice, resolve };
}

/**
 * What the device is asked for: the selection's request with the chip and the Top 100
 * weight the page shows. Without the service's capabilities the request carries neither.
 */
export function deviceRequestFor(selection: PublishedAdviceSelection): AdviceRequest {
  const { request } = selection;
  return {
    ...request,
    chip: request.chip ?? selection.chip.chip,
    top100Weight: request.top100Weight ?? selection.top100.weight,
  };
}
