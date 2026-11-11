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
 * - The total gap is each side's season total after the week before (FPL's own, net of its
 *   hits) plus its live net. A head-to-head league plays for match points, so it has none.
 */

import type { FplEntrySeason } from "../forwarder/documents";
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
 * The duel of two boards of the same week and read. `totals` are both sides' season totals
 * before the week (`seasonTotalBefore`), or null for a league that keeps no such table.
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
 * A member's season total before `gameweek`: FPL's total after the latest week before it,
 * net of the hits, or 0 for a member whose season starts with it. A season document that
 * already lists the week itself is read before it, so its live points never count twice.
 */
export function seasonTotalBefore(season: FplEntrySeason, gameweek: number): number {
  let total = 0;
  let latest = 0;
  for (const week of season.weeks) {
    if (week.event < gameweek && week.event > latest) {
      latest = week.event;
      total = week.total_points;
    }
  }
  return total;
}
