/**
 * What the device is asked for, and which solve answers it. The worker and the tests
 * come through here; nothing else knows which module solves which selection.
 */

import type { DecisionPreferences } from "../advice/decisionPreferences";
import type { PreferenceBundle } from "../advice/preferenceBundle";
import { solvePreferenceBundle } from "./preferenceBundle";
import { solveAlternatives } from "./alternatives";
import { orderedBench, viceCaptain } from "./publication/rows";
import { solveChipGains } from "./chipForecast/gains";
import type { LpSolver } from "./lp/problem";
import { DevicePlanRefused, solvePlan } from "./solve/week";
import { gainVsNoChip, weekPoints } from "./strategies/chips";
import { solveRival } from "./strategies/rival";
import { solveRivalWithTop100, solveTop100 } from "./strategies/top100";
import type {
  DeviceChip,
  DevicePlanAnswer,
  DevicePlanDocument,
  DevicePlanEntry,
  DeviceRival,
  RivalStrategy,
} from "./types";

export interface DevicePlanRequest {
  preferenceBundle?: PreferenceBundle;
  alternatives?: boolean;
  preferences?: DecisionPreferences;
  id: number;
  document: DevicePlanDocument;
  entry: DevicePlanEntry;
  /** A chip to play this week, or null for the plain plan. */
  chip?: DeviceChip | null;
  /** A rival strategy against the named rival; null for the pure-points plan. */
  strategy?: { name: RivalStrategy; rival: DeviceRival } | null;
  /** A Top 100 weight the plan is chosen on; 0 or absent for the base points. */
  top100Weight?: number;
  /**
   * The held chips whose gain this week the chip timing reads: the plain plan, then each
   * chip solved once beside it. Empty or absent asks for none.
   */
  chipGains?: DeviceChip[];
}

/**
 * The plan asked for. With a chip: the chip week and, beside it, the member's own no-chip
 * plan the chip is measured against, exactly as the server measures `gain_vs_no_chip`.
 * With a rival strategy: the banded plan with its price and labels, optionally chosen on
 * a Top 100 weight. Chips combine with neither. With chip gains: the plain plan, and each held chip's gain
 * against it, or null where its solve was refused; they too combine with nothing. The
 * plain plan is handed to `onPlan` as soon as it is solved, before any chip, and each chip
 * tried after it to `onChip`.
 */
export function solveRequest(
  solver: LpSolver,
  {
    document,
    entry,
    chip = null,
    strategy = null,
    top100Weight = 0,
    chipGains = [],
    preferences,
    alternatives = false,
    preferenceBundle,
  }: Omit<DevicePlanRequest, "id">,
  now: () => number = () => performance.now(),
  onPlan?: (plan: DevicePlanAnswer) => void,
  onChip?: (done: number, total: number) => void,
): DevicePlanAnswer {
  if (preferenceBundle) {
    if (alternatives || strategy || top100Weight || chipGains.length)
      throw new DevicePlanRefused("unsupported preference execution combination", "plan");
    return solvePreferenceBundle(
      solver,
      { document, entry, preferences, chip, bundle: preferenceBundle },
      (rules, choice) =>
        solveRequest(solver, { document, entry, preferences: rules, chip: choice }, now),
      now,
    );
  }
  if (alternatives) {
    if (
      chip !== null ||
      strategy ||
      top100Weight ||
      chipGains.length ||
      !preferences?.net_points_priority
    )
      throw new DevicePlanRefused("unsupported alternative combination", "plan");
    const baseline = solvePlan(solver, document, entry, now, null, { preferences });
    try {
      const choices = solveAlternatives(solver, document, entry, preferences);
      const held = new Set(entry.held);
      const quantized = {
        ...document,
        players: document.players.map((player) => ({
          ...player,
          expected_points: player.coefficients[2] / document.rules.expected_points_scale,
        })),
      };
      const answers = choices.map((choice, index): DevicePlanAnswer => {
        const selected = new Set(choice.squad);
        const incoming = choice.squad.filter((id) => !held.has(id));
        const outgoing = entry.held.filter((id) => !selected.has(id));
        const moves: DevicePlanAnswer["moves"] = [];
        for (const position of Object.keys(document.rules.squad_position_limits)) {
          const matches = (ids: number[]) =>
            ids
              .filter((id) =>
                document.players.some((player) => player.id === id && player.position === position),
              )
              .sort((a, b) => a - b);
          const ins = matches(incoming),
            outs = matches(outgoing);
          if (ins.length !== outs.length) throw new Error("Transfer positions do not balance.");
          ins.forEach((id, i) => moves.push({ in: id, out: outs[i]!, gain: null }));
        }
        const own = weekPoints(quantized, choice.squad, choice.startingXi, choice.captain, null);
        return {
          ...baseline,
          ...(index > 0 ? { restricted: true } : {}),
          objective_scaled: choice.objectiveScaled,
          objective: choice.netPoints,
          squad: choice.squad,
          starting_xi: choice.startingXi,
          captain: choice.captain,
          vice_captain: viceCaptain(quantized, choice.startingXi, choice.captain),
          bench: orderedBench(quantized, choice.squad, choice.startingXi),
          transfers_in: incoming,
          transfers_out: outgoing,
          transfer_hit_points: choice.hitPoints,
          expected_own_points: own,
          moves,
          expected_gain_vs_hold: own - baseline.hold_points,
          bank_after_tenths: choice.bankTenths,
          free_transfers_after: choice.freeTransfersAfter,
        };
      });
      const [main, ...rest] = answers;
      return { ...(main ?? baseline), alternatives: rest };
    } catch (error) {
      if (!(error instanceof DevicePlanRefused)) throw error;
      return { ...baseline, alternatives: [] };
    }
  }
  if (preferences && (chipGains.length || top100Weight || strategy))
    throw new DevicePlanRefused("unsupported preference combination", "plan");
  if (chipGains.length > 0) {
    if (chip !== null || strategy !== null || top100Weight !== 0) {
      throw new DevicePlanRefused("chip gains with a chip, a rival strategy or a weight", "plan");
    }
    return solveChipGains(solver, document, entry, chipGains, now, onPlan, onChip);
  }
  if (top100Weight !== 0) {
    if (chip !== null) throw new DevicePlanRefused("a weight with a chip", "plan");
    if (strategy !== null)
      return solveRivalWithTop100(
        solver,
        document,
        entry,
        strategy.rival,
        strategy.name,
        top100Weight,
        now,
      );
    return solveTop100(solver, document, entry, top100Weight, now);
  }
  if (strategy !== null) {
    if (chip !== null) throw new DevicePlanRefused("a chip with a rival strategy", "plan");
    return solveRival(solver, document, entry, strategy.rival, strategy.name, now);
  }
  if (chip === null) return solvePlan(solver, document, entry, now, null, { preferences });
  const started = now();
  const without = solvePlan(solver, document, entry, now, null, { preferences });
  const answer = solvePlan(solver, document, entry, now, chip, { preferences });
  return {
    ...answer,
    gain_vs_no_chip: gainVsNoChip(answer, without),
    seconds: (now() - started) / 1000,
  };
}
