/**
 * A rival strategy on the device: `advice._advise_against_rival` restated.
 *
 * The member's own squad is still the only starting point; the rival contributes a
 * constraint (their public eleven) and the comparison labels, nothing else. The band is
 * the catalogue's overlap floor or ceiling on how many of the rival's eleven the decided
 * fifteen holds. Two candidates, one decision rule: within the free transfers, the
 * strictest level the cap reaches (a floor relaxed downward, a ceiling upward), no hits;
 * with hits, the declared target. The one with the higher net expected points is the
 * plan, the other is published beside it. The price is the member's own pure-points plan
 * solved at the game's charge, floored at the best plan solved here, less the banded
 * plan, both net of hits. Every solve is proved, so the price carries its ceiling.
 */

import type { MemberWeekOptions } from "../lp/memberWeek";
import type { LpSolver } from "../lp/problem";
import {
  answerFrom,
  DevicePlanRefused,
  inSolverOrder,
  solveWeek,
  type WeekSolution,
} from "../solve/week";
import type {
  DevicePlanAnswer,
  DevicePlanDocument,
  DevicePlanEntry,
  DeviceRival,
  DeviceRivalFields,
  DeviceRivalPlanKind,
  RivalStrategy,
} from "../types";
import { weekPoints } from "./chips";

export interface OverlapBandRule {
  overlap_floor: number | null;
  overlap_ceiling: number | null;
}

/**
 * The catalogue's bands as the device knows them, for a document published before the
 * rules carried them. The fixture's document, written by the producer from the catalogue,
 * is held to this table by the parity test.
 */
export const CATALOGUE_BANDS: Record<RivalStrategy, OverlapBandRule> = {
  "ortak-koru": { overlap_floor: 9, overlap_ceiling: null },
  "fark-yarat": { overlap_floor: null, overlap_ceiling: 5 },
};

export function bandFor(document: DevicePlanDocument, strategy: RivalStrategy): OverlapBandRule {
  return document.rules.strategies?.[strategy] ?? CATALOGUE_BANDS[strategy];
}

/** The game's charge per paid transfer on the objective scale, as the producer scales it. */
function chargeScaled(document: DevicePlanDocument): number {
  const { rules } = document;
  return (
    rules.hit_charged_scaled ?? Math.round(rules.hit_points_charged * rules.expected_points_scale)
  );
}

interface Candidate {
  solution: WeekSolution;
  applied: number;
  kind: DeviceRivalPlanKind;
}

/** What a candidate pays in hits: the arrivals beyond the free transfers, at the charge. */
function hitsOf(
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  solution: WeekSolution,
): number {
  const held = new Set(entry.held);
  const arrivals = solution.squad.filter((id) => !held.has(id)).length;
  return Math.max(0, arrivals - entry.free_transfers) * document.rules.hit_points_charged;
}

/** A candidate's net expected points: the eleven with the captain, less its hits. */
function netOf(
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  solution: WeekSolution,
): number {
  return (
    weekPoints(document, solution.squad, solution.startingXi, solution.captain, null) -
    hitsOf(document, entry, solution)
  );
}

/**
 * The banded plan under the transfer cap, at the strictest level the cap reaches. A
 * floor is relaxed downward (nine, eight, ... one); a ceiling upward (five, six, ...
 * eleven). Each level is one solve; an unsatisfiable level is the solver's own refusal.
 */
function withinFreeTransfers(
  solver: LpSolver,
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  rivalIds: readonly number[],
  band: OverlapBandRule,
  transferCap: number,
): Candidate | null {
  const levels: Array<{ minimum?: number; maximum?: number; level: number }> = [];
  if (band.overlap_floor !== null) {
    for (let level = band.overlap_floor; level >= 1; level -= 1)
      levels.push({ minimum: level, level });
  } else if (band.overlap_ceiling !== null) {
    for (let level = band.overlap_ceiling; level <= rivalIds.length; level += 1) {
      levels.push({ maximum: level, level });
    }
  }
  for (const { level, ...bounds } of levels) {
    const solution = solveWeek(solver, document, entry, {
      overlap: { ids: rivalIds, ...bounds },
      transferCap,
    });
    if (solution) return { solution, applied: level, kind: "within_free_transfers" };
  }
  return null;
}

export function solveRival(
  solver: LpSolver,
  published: DevicePlanDocument,
  entry: DevicePlanEntry,
  rival: DeviceRival,
  strategy: RivalStrategy,
  now: () => number = () => performance.now(),
): DevicePlanAnswer {
  const started = now();
  const document = inSolverOrder(published);
  const known = new Set(document.players.map((p) => p.id));
  const rivalIds = [...rival.starting_xi].sort((a, b) => a - b);
  // A rival score cannot treat missing players as zero, and the rival's captain is one
  // of their eleven; the server refuses both before any solve.
  if (!rivalIds.includes(rival.captain) || rivalIds.some((id) => !known.has(id))) {
    throw new DevicePlanRefused("rival not in the table", "plan");
  }
  const band = bandFor(document, strategy);
  const target = band.overlap_floor ?? band.overlap_ceiling;
  if (target === null) throw new DevicePlanRefused("strategy has no band", "plan");
  const transferCap = Math.max(
    1,
    Math.min(entry.free_transfers, document.rules.max_free_transfers),
  );

  const withinFree = withinFreeTransfers(solver, document, entry, rivalIds, band, transferCap);
  const target_options: MemberWeekOptions = {
    overlap: {
      ids: rivalIds,
      ...(band.overlap_floor !== null ? { minimum: band.overlap_floor } : {}),
      ...(band.overlap_ceiling !== null ? { maximum: band.overlap_ceiling } : {}),
    },
  };
  const hitsSolution = solveWeek(solver, document, entry, target_options);
  const withHits: Candidate | null = hitsSolution
    ? { solution: hitsSolution, applied: target, kind: "with_hits" }
    : null;
  if (withinFree === null && withHits === null) {
    throw new DevicePlanRefused("band unsatisfiable", "plan");
  }
  const net = (candidate: Candidate) => netOf(document, entry, candidate.solution);
  let chosen: Candidate;
  let other: Candidate | null;
  if (withinFree !== null && (withHits === null || net(withinFree) >= net(withHits))) {
    chosen = withinFree;
    other = withHits;
  } else {
    chosen = withHits!;
    other = withinFree;
  }

  // The price tag's anchor: the pure-points plan at the game's charge, floored at the
  // best plan solved here so a constraint is never published as a discount.
  const pricing = solveWeek(solver, document, entry, { hitCostScaled: chargeScaled(document) });
  if (pricing === null) throw new DevicePlanRefused("pricing control infeasible", "plan");
  const strategyNet = net(chosen);
  const nets = [netOf(document, entry, pricing), strategyNet];
  if (other !== null) nets.push(net(other));
  const controlNet = Math.max(...nets);

  const answer = answerFrom(solver, document, entry, chosen.solution, {});
  const points = new Map(document.players.map((p) => [p.id, p.expected_points]));
  const rivalExpected =
    rivalIds.reduce((total, id) => total + (points.get(id) ?? 0), 0) +
    (points.get(rival.captain) ?? 0);
  const fields: DeviceRivalFields = {
    mode: strategy,
    rival_entry_id: rival.entry_id,
    expected_points_cost: controlNet - strategyNet,
    expected_points_cost_ceiling: controlNet - strategyNet,
    overlap_count: chosen.solution.squad.filter((id) => rivalIds.includes(id)).length,
    transfer_cap: transferCap,
    overlap_target: target,
    overlap_applied: chosen.applied,
    plan_kind: chosen.kind,
    alternative_plan:
      other === null
        ? null
        : {
            kind: other.kind,
            overlap_applied: other.applied,
            transfer_hit_points: hitsOf(document, entry, other.solution),
            expected_points_cost: controlNet - net(other),
            expected_points_cost_ceiling: controlNet - net(other),
          },
    // A mean and only a mean: the two elevens on the same table, net of the plan's hits.
    expected_gap_vs_rival: answer.expected_own_points - answer.transfer_hit_points - rivalExpected,
    captain_agreement: answer.captain === rival.captain,
  };
  return { ...answer, rival: fields, seconds: (now() - started) / 1000 };
}
