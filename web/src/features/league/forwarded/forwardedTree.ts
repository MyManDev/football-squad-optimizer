/**
 * The tree a forwarded page's shared hooks read (`useDevicePlan`, `useMemberLiveScore`): the
 * capture's table the page already read, and every other document as not published, since
 * nothing is published for a forwarded league or entry.
 */

import { LeagueDataMissing, type LeagueTree } from "../data";
import type { PublishedLeague } from "../directory";
import type { DevicePlanDocument } from "../device/types";
import type { LeagueViewEnvelope } from "../types";

/** The tree of a forwarded page: the capture's table it read, and nothing published. */
export function forwardedTree(
  league: PublishedLeague,
  table: LeagueViewEnvelope<DevicePlanDocument>,
): LeagueTree {
  const unpublished = (relative: string) => () => Promise.reject(new LeagueDataMissing(relative));
  return {
    league,
    async devicePlan(capture) {
      if (capture !== table.payload.source_snapshot_id) {
        throw new LeagueDataMissing(`device/${capture}/device-plan.json`);
      }
      return table;
    },
    members: unpublished("members.json"),
    entrySquad: (entryId) => Promise.reject(new LeagueDataMissing(`entries/${entryId}.json`)),
    entryAdvice: unpublished("advice"),
    entryAdviceEvidence: unpublished("advice"),
    entryAdviceChip: unpublished("advice"),
    entryAdviceTop100: unpublished("advice"),
    entryAdviceIndex: unpublished("advice"),
    scoreboard: unpublished("scoreboard.json"),
    raw: (relative) => Promise.reject(new LeagueDataMissing(relative)),
  };
}
