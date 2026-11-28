/** Exact pool reduction for the plain, frozen-price horizon, retaining original indices. */
import type { DevicePlanDocument, DevicePlanEntry } from "../types";
import type { HorizonInputs } from "./horizon";

export interface HorizonPoolReduction {
  /** Indices in the full, unchanged solver-order document, never compacted ranks. */
  indices: number[];
  before: number;
  after: number;
  purchaseUnionLimit: number;
  fullClubUnionLimit: number;
}

/**
 * Let N be squad size, C the club limit and T = weekly transfer cap * window.
 * A dropped p is not held initially. Any plan containing p therefore buys p at
 * least once. Among dominators q which are also absent initially, at most T-1
 * distinct q can occur anywhere in that plan's initial-plus-window squad union.
 * Removing p leaves at most N+T-1 distinct players in that union. Thus at most
 * F=floor((N+T-1)/C) different clubs other than p's can ever be full while p is
 * held: each such club consumes C distinct players from the p-free union, and
 * club identities are fixed. A q from p's own club has no club obstruction.
 *
 * Group dominators by club. Discard the F largest groups from clubs other than
 * p's, a worst-case bound on every full-club obstruction over the WHOLE window.
 * If more than T-1 q remain, one is absent from the entire plan union and its
 * club is never full in a p-held week (or is p's club). Single-week counts, or
 * q merely being absent in p-held weeks, would not establish this result.
 *
 * Replace p by this same q in every held week and copy p's exact i/o/x/c pattern.
 * Neither is an initial lot; q was never held, including adjacent weeks. Every
 * transfer count, paid hit and FT state is unchanged. With frozen buy prices,
 * bank(q)-bank(p) = (buy(p)-buy(q))*held(p) >= 0 each week. Nonnegative remaining
 * lot values also keep bank below the original initial-wealth bound. Position,
 * lineup and captain constraints persist, and the club argument covers all
 * affected weeks. No primary coefficient decreases, including bench/squad
 * coefficients and every positive discount weight. If primary ties, captain,
 * starter and squad rank sums never worsen; the last tier strictly improves
 * because q's ORIGINAL rank is smaller and p is held at least once. Therefore
 * NO full lexicographic optimum contains p, so all separately certified p can
 * be removed together, even when one dominator is itself removable. Dominance
 * is a strict acyclic order because original ranks strictly decrease.
 *
 * This is only for the plain horizon dispatched without chip/rival/preferences.
 * Original holdings/sale lots, explicit protected players and grandfathered
 * club cases are never pruned. A future model with additional pinned-player
 * constraints needs its own exchange proof before using this reduction.
 */
export function reduceHorizonPool(
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  inputs: HorizonInputs,
  window: 3 | 5,
  protectedPlayerIds: readonly number[] = [],
): HorizonPoolReduction {
  const { players, rules } = document;
  const all = players.map((_, index) => index);
  const purchases = inputs.rules.max_transfers_per_gameweek * window;
  const fullClubs = Math.floor((rules.squad_size + purchases - 1) / rules.max_players_per_team);
  const result = (indices: number[]): HorizonPoolReduction => ({
    indices,
    before: players.length,
    after: indices.length,
    purchaseUnionLimit: purchases,
    fullClubUnionLimit: fullClubs,
  });
  const held = new Set(entry.held);
  const heldClubs = new Map<string, number>();
  for (const player of players)
    if (held.has(player.id)) heldClubs.set(player.team, (heldClubs.get(player.team) ?? 0) + 1);
  if (
    !Number.isSafeInteger(purchases) ||
    purchases < 1 ||
    !Number.isSafeInteger(rules.squad_size) ||
    rules.squad_size < 1 ||
    !Number.isSafeInteger(rules.max_players_per_team) ||
    rules.max_players_per_team < 1 ||
    held.size !== rules.squad_size ||
    entry.held.some((id) => !players.some((player) => player.id === id)) ||
    players.some((player) => !Number.isSafeInteger(player.buy_tenths) || player.buy_tenths < 0) ||
    Object.values(entry.sell_tenths).some((value) => !Number.isSafeInteger(value) || value < 0) ||
    [...heldClubs.values()].some((count) => count > rules.max_players_per_team)
  )
    return result(all);
  const protectedIds = new Set([
    ...entry.held,
    ...Object.keys(entry.sell_tenths).map(Number),
    ...protectedPlayerIds,
  ]);
  const weeks = inputs.weeks
    .slice(0, window)
    .map((week) => new Map(week.players.map((player) => [player.id, player.coefficients])));
  const indices = all.filter((p) => {
    const player = players[p]!;
    if (protectedIds.has(player.id)) return true;
    const byClub = new Map<string, number>();
    for (let q = 0; q < p; q += 1) {
      const other = players[q]!;
      if (
        protectedIds.has(other.id) ||
        other.position !== player.position ||
        other.buy_tenths > player.buy_tenths ||
        weeks.some((week) => {
          const original = week.get(player.id)!;
          return week.get(other.id)!.some((coefficient, family) => coefficient < original[family]!);
        })
      )
        continue;
      byClub.set(other.team, (byClub.get(other.team) ?? 0) + 1);
    }
    const dominatedBy = [...byClub.values()].reduce((sum, count) => sum + count, 0);
    const blockedByFullClubs = [...byClub.entries()]
      .filter(([club]) => club !== player.team)
      .map(([, count]) => count)
      .sort((a, b) => b - a)
      .slice(0, fullClubs)
      .reduce((sum, count) => sum + count, 0);
    return dominatedBy - blockedByFullClubs <= purchases - 1;
  });
  return result(indices);
}
