/**
 * The member's live week (#1008, source A) from what the page holds: the forwarder's live
 * week and the member's current week from their bundle, each pick's position, club and name
 * from the capture's table by element id (#981 step 1), and each club's id from the site's
 * calendar by the club's name. The score is `scoreMemberWeek`'s; nothing is recorded.
 */

import type { FixturesPayload } from "../../fixtures/types";
import { scoreMemberWeek, type LiveWeekScore } from "../../liveScore/officialScoring";
import type { MemberWeek, Position, WeekLive } from "../../liveScore/weekLive";
import { forecastSource } from "../device/chipForecast/member";
import { DEVICE_PLAN_TABLE_CONTRACT_VERSION, type DevicePlanDocument } from "../device/types";

const POSITIONS: readonly string[] = ["GK", "DEF", "MID", "FWD"];

/**
 * Why the week is not shown:
 *
 * - `other_week`: the member's week is not the live document's;
 * - `other_season`: the table or the calendar is another season's;
 * - `table_without_element_ids`: the table is the tree's copy, which names no element ids;
 * - `pick_not_in_table`: a pick the table does not name, or names with no position;
 * - `club_not_in_calendar`: a pick's club the calendar does not name, or a calendar whose
 *   clubs cannot be read;
 * - `score_refused`: the scorer refused the week, for the reason in `detail`.
 */
export type MemberLiveRefusal =
  | "other_week"
  | "other_season"
  | "table_without_element_ids"
  | "pick_not_in_table"
  | "club_not_in_calendar"
  | "score_refused";

export interface MemberLiveScore {
  gameweek: number;
  score: Extract<LiveWeekScore, { refused: false }>;
  /** The fifteen's names by element id, as the table states them. */
  names: ReadonlyMap<number, string>;
}

export type MemberLiveResult =
  { ok: true; live: MemberLiveScore } | { ok: false; reason: MemberLiveRefusal; detail?: string };

export function memberLiveScore({
  live,
  member,
  table,
  fixtures,
}: {
  live: WeekLive;
  member: MemberWeek;
  table: DevicePlanDocument;
  fixtures: FixturesPayload;
}): MemberLiveResult {
  if (member.gameweek !== live.gameweek) return { ok: false, reason: "other_week" };
  if (table.season !== live.season || fixtures.season !== live.season) {
    return { ok: false, reason: "other_season" };
  }
  if (table.contract_version !== DEVICE_PLAN_TABLE_CONTRACT_VERSION) {
    return { ok: false, reason: "table_without_element_ids" };
  }
  const players = new Map(table.players.map((player) => [player.element_id, player]));
  if (players.size !== table.players.length) return { ok: false, reason: "pick_not_in_table" };
  const calendar = forecastSource(fixtures);
  if (calendar === null || calendar.unavailable_reason !== null) {
    return { ok: false, reason: "club_not_in_calendar" };
  }
  const resolved = new Map<number, { position: Position; club: number }>();
  const names = new Map<number, string>();
  for (const pick of member.pick_order) {
    const player = players.get(pick);
    if (player === undefined || !POSITIONS.includes(player.position)) {
      return { ok: false, reason: "pick_not_in_table" };
    }
    const club = calendar.club_ids_by_name.get(player.team);
    if (club === undefined) return { ok: false, reason: "club_not_in_calendar" };
    resolved.set(pick, { position: player.position as Position, club });
    names.set(pick, player.short_name.trim() || player.name);
  }
  const score = scoreMemberWeek(
    {
      ...live,
      elements: live.elements.map((element) => {
        const known = resolved.get(element.element_id);
        return known === undefined ? element : { ...element, ...known };
      }),
    },
    member,
  );
  if (score.refused) return { ok: false, reason: "score_refused", detail: score.reason };
  return { ok: true, live: { gameweek: live.gameweek, score, names } };
}
