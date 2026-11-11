/**
 * The LIVE page's duel: the member's board beside one rival's, read from the same live
 * document (the synthesis of 2026-11-11, section 3.2). Never a second squad: each player
 * either side owns counts for the side that counts him, so the duel is the players whose
 * multipliers differ.
 *
 * - A side's multiplier of a player is what its score takes of his points: 0 where it does
 *   not count him (or does not own him), 1, or the armband's 2 or 3.
 * - His swing is his points times the member's multiplier less the rival's. The swings and
 *   the two transfer costs make the margin exactly:
 *   Σ swing − (hit_member − hit_rival) = net_member − net_rival.
 * - Players both sides own at the same multiplier make no difference and are only counted.
 * - The total gap is each side's total in the league's own table before the week plus its
 *   live net. A league counts its totals from its own first week, which need not be the
 *   season's, so the totals come from the table the league publishes, never from FPL's
 *   season totals. A head-to-head league plays for match points, so it has none.
 */

import type { LeagueMembers } from "../types";
import type { LiveBoard, LiveRow, Multiplier } from "./liveBoard";

export type DuelStatus = "ahead" | "level" | "behind";

export interface DuelSwing {
  elementId: number;
  /** The row the name and shirt come from: the member's where he owns the player. */
  row: LiveRow;
  points: number;
  member: Multiplier;
  rival: Multiplier;
  /** points × (member − rival). */
  swing: number;
}

export interface LiveDuel {
  /** The member's net less the rival's. */
  margin: number;
  status: DuelStatus;
  /** Players the member's score takes more of, the biggest swing first. */
  yours: DuelSwing[];
  /** Players the rival's score takes more of, the biggest swing first. */
  theirs: DuelSwing[];
  /** Players both own at the same multiplier. */
  shared: number;
  /** Counted players with a fixture still to finish, on each side. */
  left: { member: number; rival: number };
  /** The season totals' gap if the week ended now; null where there is none to give. */
  totalGap: number | null;
}

export function duelStatus(margin: number): DuelStatus {
  return margin > 0 ? "ahead" : margin < 0 ? "behind" : "level";
}

const bySwing = (a: DuelSwing, b: DuelSwing) =>
  Math.abs(b.swing) - Math.abs(a.swing) || b.points - a.points || a.row.pick - b.row.pick;

/**
 * The duel of two boards of the same week and read. `totals` are both sides' league totals
 * before the week (`leagueTotalsBefore`), or null where there are none to give.
 */
export function liveDuel(
  member: LiveBoard,
  rival: LiveBoard,
  totals: { member: number; rival: number } | null = null,
): LiveDuel {
  const mine = new Map(member.rows.map((row) => [row.elementId, row]));
  const theirs = new Map(rival.rows.map((row) => [row.elementId, row]));
  const swings: DuelSwing[] = [];
  let shared = 0;
  for (const elementId of new Set([...mine.keys(), ...theirs.keys()])) {
    const own = mine.get(elementId);
    const other = theirs.get(elementId);
    const row = (own ?? other)!;
    const memberMultiplier: Multiplier = own?.multiplier ?? 0;
    const rivalMultiplier: Multiplier = other?.multiplier ?? 0;
    if (memberMultiplier === rivalMultiplier) {
      if (own !== undefined && other !== undefined) shared += 1;
      continue;
    }
    swings.push({
      elementId,
      row,
      points: row.points,
      member: memberMultiplier,
      rival: rivalMultiplier,
      swing: row.points * (memberMultiplier - rivalMultiplier),
    });
  }
  const margin = member.net - rival.net;
  return {
    margin,
    status: duelStatus(margin),
    yours: swings.filter((swing) => swing.member > swing.rival).sort(bySwing),
    theirs: swings.filter((swing) => swing.rival > swing.member).sort(bySwing),
    shared,
    left: { member: member.left, rival: rival.left },
    totalGap: totals === null ? null : totals.member + member.net - (totals.rival + rival.net),
  };
}

/**
 * Two members' totals in the league's own table before `gameweek`, from the members document
 * the league publishes: its totals where it was scored through the week before, or its totals
 * less the week's own net (its points less its hit) where it was scored through `gameweek`
 * itself, so the live net never counts twice. A table scored through any other week, a member
 * it has no total or week for, or a league that publishes none (a forwarded league, whose
 * table FPL updates while the week is played) gives none.
 */
export function leagueTotalsBefore(
  table: Pick<LeagueMembers, "scored_gameweek" | "members"> | null,
  gameweek: number,
  memberId: number,
  rivalId: number,
): { member: number; rival: number } | null {
  if (table === null || table.scored_gameweek === null) return null;
  const through = table.scored_gameweek;
  if (through !== gameweek - 1 && through !== gameweek) return null;
  const before = (entryId: number): number | null => {
    const row = table.members.find((member) => member.entry_id === entryId);
    if (row === undefined || row.total_points === null) return null;
    if (through === gameweek - 1) return row.total_points;
    if (row.gameweek_points === null || row.transfer_cost === null) return null;
    return row.total_points - (row.gameweek_points - row.transfer_cost);
  };
  const member = before(memberId);
  const rival = before(rivalId);
  return member === null || rival === null ? null : { member, rival };
}
