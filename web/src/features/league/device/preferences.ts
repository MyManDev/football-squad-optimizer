/** Hard one-week rules, shared by every device alternative. */
import { checkedPreferences, type DecisionPreferences } from "../advice/decisionPreferences";
import { rebuilds } from "./strategies/chips";
import type { DeviceChip, DevicePlanDocument, DevicePlanEntry } from "./types";
import { row, term, type LpRow } from "./lp/problem";

export function oneWeekPreferences(value?: DecisionPreferences): DecisionPreferences | undefined {
  if (!value) return undefined;
  const p = checkedPreferences(value);
  if (
    p.wildcard_week ||
    p.scenario ||
    p.week_rules?.some((r) => r.week !== 1) ||
    p.frozen_weeks?.some((r) => r.week !== 1) ||
    (p.min_bank?.week && p.min_bank.week !== 1)
  )
    throw new Error("The device does not support this preference window.");
  return p;
}

export function hardPreferenceRows(
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  value: DecisionPreferences | undefined,
  chip: DeviceChip | null,
): LpRow[] {
  const p = oneWeekPreferences(value);
  if (!p) return [];
  const rows: LpRow[] = [];
  const held = new Set(entry.held);
  const index = new Map(document.players.map((player, i) => [player.id, i]));
  const add = (terms: ReturnType<typeof term>[], sense: "=" | "<=" | ">=", rhs: number) =>
    rows.push(row(`pref${rows.length}`, terms, sense, rhs));
  const impossible = () => add([], "=", 1);
  const member = (id: number) => {
    const i = index.get(id);
    if (i === undefined) throw new Error("A preference names an unknown player.");
    return `s${i}`;
  };
  const arrivals = document.players.flatMap((player, i) =>
    held.has(player.id) ? [] : [term(1, `s${i}`)],
  );
  for (const rules of [p, ...(p.week_rules ?? []).map((row) => row.rules)]) {
    for (const id of rules.keep_players) {
      if (!held.has(id)) throw new Error("Only a held player can be kept.");
      add([term(1, member(id))], "=", 1);
    }
    for (const id of rules.include_players ?? []) add([term(1, member(id))], "=", 1);
    for (const id of rules.avoid_players) add([term(1, member(id))], "=", 0);
    if ("buy_players" in rules) {
      for (const id of rules.buy_players ?? []) {
        if (held.has(id)) throw new Error("A held player cannot be bought.");
        add([term(1, member(id))], "=", 1);
      }
    }
    if (rules.no_hits && !rebuilds(chip)) add([term(1, "paid")], "=", 0);
    if (rules.save_chips && chip !== null) impossible();
    if (rules.hold_transfers) {
      add(arrivals, "=", 0);
      if (rebuilds(chip)) impossible();
    }
    for (const count of rules.club_counts ?? []) {
      if (!document.players.some((player) => player.team === count.club))
        throw new Error("A preference names an unknown club.");
      add(
        document.players.flatMap((player, i) =>
          player.team === count.club && (count.scope !== "transfers_in" || !held.has(player.id))
            ? [term(1, `s${i}`)]
            : [],
        ),
        "=",
        count.count,
      );
    }
  }
  if (p.hold_opening_transfers) {
    add(arrivals, "=", 0);
    if (rebuilds(chip)) impossible();
  }
  if (p.max_hit_points !== undefined && !rebuilds(chip))
    add([term(document.rules.hit_points_charged, "paid")], "<=", p.max_hit_points);
  const floor = Math.max(p.min_opening_bank_tenths ?? 0, p.min_bank?.tenths ?? 0);
  if (floor) {
    if (chip === "freehit") {
      if (entry.bank_tenths < floor) impossible();
    } else {
      const sell = (id: number, buy: number) => entry.sell_tenths[String(id)] ?? buy;
      const proceeds = document.players.reduce(
        (sum, player) => sum + (held.has(player.id) ? sell(player.id, player.buy_tenths) : 0),
        0,
      );
      add(
        document.players.map((player, i) =>
          term(
            held.has(player.id) ? sell(player.id, player.buy_tenths) : player.buy_tenths,
            `s${i}`,
          ),
        ),
        "<=",
        entry.bank_tenths + proceeds - floor,
      );
    }
  }
  for (const frozen of p.frozen_weeks ?? []) {
    if (frozen.chip !== chip) impossible();
    const incoming = new Set(frozen.transfers_in),
      outgoing = new Set(frozen.transfers_out);
    for (const id of incoming) {
      member(id);
      if (held.has(id)) impossible();
    }
    for (const id of outgoing) {
      member(id);
      if (!held.has(id)) impossible();
    }
    document.players.forEach((player, i) =>
      add(
        [term(1, `s${i}`)],
        "=",
        Number(incoming.has(player.id) || (held.has(player.id) && !outgoing.has(player.id))),
      ),
    );
    if (frozen.starting_xi) {
      const starters = new Set(frozen.starting_xi);
      for (const id of starters) member(id);
      document.players.forEach((player, i) =>
        add([term(1, `x${i}`)], "=", Number(starters.has(player.id))),
      );
      const captainIndex = index.get(frozen.captain!);
      if (captainIndex === undefined) impossible();
      else add([term(1, `c${captainIndex}`)], "=", 1);
    }
  }
  return rows;
}
