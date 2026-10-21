import { memberWeek, weekLive, WeekLiveError, type Position } from "./weekLive";

export type LiveWeekScore =
  | {
      refused: false;
      net: number;
      gross: number;
      scoring_basis: "official_autosub_captain_v2";
      transfer_cost: number;
      source_time: string;
      fixtures_finished: number;
      fixtures_total: number;
      bonus_confirmed: boolean;
      captain: number | null;
      captain_bonus_points: number;
      counted: number[];
      autosubs: [number, number][];
    }
  | { refused: true; reason: string };

const counts = (positions: Position[]): Record<Position, number> => {
  const found = { GK: 0, DEF: 0, MID: 0, FWD: 0 };
  for (const position of positions) found[position] += 1;
  return found;
};
const legal = (c: Record<Position, number>) =>
  c.GK === 1 && c.DEF >= 3 && c.DEF <= 5 && c.MID >= 2 && c.MID <= 5 && c.FWD >= 1 && c.FWD <= 3;

/** Pure display calculation. The caller resolves element ids and supplies the same week's picks. */
export function scoreMemberWeek(input: unknown, member: unknown): LiveWeekScore {
  try {
    const document = weekLive(input);
    const picks = memberWeek(member, document.gameweek);
    const elements = new Map(document.elements.map((element) => [element.element_id, element]));
    const squad = picks.pick_order.map((id) => {
      const element = elements.get(id);
      if (!element) throw new WeekLiveError("missing_pick");
      if (!element.position || !element.club) throw new WeekLiveError("unresolved_pick");
      return { ...element, position: element.position, club: element.club };
    });
    const byId = new Map(squad.map((element) => [element.element_id, element]));
    const position = (id: number) => byId.get(id)!.position;
    const total = counts(squad.map((element) => element.position));
    const starters = picks.pick_order.slice(0, 11);
    const bench = picks.pick_order.slice(11);
    let nominal = counts(starters.map(position));
    if (total.GK !== 2 || total.DEF !== 5 || total.MID !== 5 || total.FWD !== 3 || !legal(nominal))
      throw new WeekLiveError("invalid_formation");
    const complete = (id: number) =>
      document.fixtures.every(
        (fixture) =>
          (fixture.home_club !== byId.get(id)!.club && fixture.away_club !== byId.get(id)!.club) ||
          fixture.finished,
      );
    const played = (id: number) => byId.get(id)!.minutes > 0 || byId.get(id)!.card_shown;
    const eligible = (id: number) => !played(id) && complete(id);
    const points = (id: number) => byId.get(id)!.points;
    const slots = [...starters];
    const autosubs: [number, number][] = [];
    const change = (out: number, incoming: number) => {
      slots[slots.indexOf(out)] = incoming;
      autosubs.push([out, incoming]);
    };
    const keeper = starters.find((id) => position(id) === "GK")!;
    const reserveKeeper = bench.find((id) => position(id) === "GK")!;
    if (eligible(keeper) && played(reserveKeeper)) change(keeper, reserveKeeper);
    const missing = starters.filter((id) => position(id) !== "GK" && eligible(id));
    for (const reserve of bench) {
      if (position(reserve) === "GK") continue;
      if (!played(reserve)) {
        if (!complete(reserve)) break;
        continue;
      }
      for (const out of [...missing]) {
        const next = { ...nominal };
        next[position(out)] -= 1;
        next[position(reserve)] += 1;
        if (!legal(next)) continue;
        change(out, reserve);
        nominal = next;
        missing.splice(missing.indexOf(out), 1);
        break;
      }
    }
    const counted = slots.filter((id) => played(id) || !complete(id));
    let captain: number | null = null;
    if (byId.get(picks.captain)!.minutes > 0 || !complete(picks.captain)) captain = picks.captain;
    else if (
      counted.includes(picks.vice) &&
      (byId.get(picks.vice)!.minutes > 0 || !complete(picks.vice))
    )
      captain = picks.vice;
    const bonus = captain === null ? 0 : points(captain);
    const benchBoost = picks.active_chip === "bboost";
    const scored = benchBoost ? [...picks.pick_order] : counted;
    const grossInteger =
      scored.reduce((sum, id) => sum + BigInt(points(id)), 0n) +
      BigInt(bonus) * (picks.active_chip === "3xc" ? 2n : 1n);
    const gross = Number(grossInteger);
    const net = Number(grossInteger - BigInt(picks.transfer_cost));
    if (!Number.isSafeInteger(gross) || !Number.isSafeInteger(net))
      throw new WeekLiveError("score_overflow");
    const finished = document.fixtures.filter((fixture) => fixture.finished).length;
    return {
      refused: false,
      gross,
      net,
      scoring_basis: "official_autosub_captain_v2",
      transfer_cost: picks.transfer_cost,
      source_time: document.source_time,
      fixtures_finished: finished,
      fixtures_total: document.fixtures.length,
      bonus_confirmed: finished === document.fixtures.length,
      captain,
      captain_bonus_points: bonus,
      counted: scored,
      autosubs: benchBoost ? [] : autosubs,
    };
  } catch (error) {
    if (error instanceof WeekLiveError) return { refused: true, reason: error.message };
    throw error;
  }
}
