/** The plain captured-calendar horizon, with the server's weekly resource accounting. */
import type { DevicePlanDocument, DevicePlanEntry } from "../types";
import { DevicePlanRefused } from "../solve/week";
import { row, term, type LpProblem, type LpTerm } from "./problem";

export interface HorizonPlayer {
  id: number;
  buy_tenths: number;
  expected_points: number;
  coefficients: [number, number, number];
  appearance_probability?: number;
}

export interface HorizonInputs {
  contract_version: "league_device_horizon_v1";
  windows: number[];
  rules: {
    max_transfers_per_gameweek: number;
    free_transfer_accrual: number;
    bench_weight: number;
    objective_weight_scale: number;
    horizon_discount_factor: number;
    banked_transfer_value_scaled: number;
    acquisition_sell_on_fee: number;
  };
  weeks: Array<{ gameweek: number; discount_weight: number; players: HorizonPlayer[] }>;
}

function fail(): never {
  throw new DevicePlanRefused("unsupported horizon inputs", "plan");
}

/** Old documents still solve H1; a horizon solve requires its own complete contract. */
export function horizonInputs(document: DevicePlanDocument, window: 3 | 5): HorizonInputs {
  const candidate = (document as DevicePlanDocument & { horizon?: HorizonInputs }).horizon;
  if (
    !candidate ||
    candidate.contract_version !== "league_device_horizon_v1" ||
    !Array.isArray(candidate.windows) ||
    !candidate.windows.includes(window) ||
    !candidate.rules ||
    candidate.rules.max_transfers_per_gameweek !== 1 ||
    candidate.rules.free_transfer_accrual !== 1 ||
    candidate.rules.banked_transfer_value_scaled !== 0 ||
    !Number.isSafeInteger(candidate.rules.objective_weight_scale) ||
    candidate.rules.objective_weight_scale < 1 ||
    !Number.isFinite(candidate.rules.bench_weight) ||
    candidate.rules.bench_weight < 0 ||
    candidate.rules.bench_weight > 1 ||
    !Number.isFinite(candidate.rules.horizon_discount_factor) ||
    candidate.rules.horizon_discount_factor <= 0 ||
    !Number.isFinite(candidate.rules.acquisition_sell_on_fee) ||
    !Array.isArray(candidate.weeks) ||
    candidate.weeks.length < window
  )
    return fail();
  const ids = document.players.map((player) => player.id);
  if (new Set(ids).size !== ids.length) return fail();
  for (const [index, week] of candidate.weeks.slice(0, window).entries()) {
    if (
      week.gameweek !== document.gameweek + index ||
      !Number.isSafeInteger(week.discount_weight) ||
      week.discount_weight < 1 ||
      !Array.isArray(week.players) ||
      week.players.length !== ids.length
    )
      return fail();
    const points = new Map(week.players.map((player) => [player.id, player]));
    if (points.size !== ids.length) return fail();
    for (const player of document.players) {
      const value = points.get(player.id);
      if (
        !value ||
        value.buy_tenths !== player.buy_tenths ||
        !Number.isFinite(value.expected_points) ||
        !Array.isArray(value.coefficients) ||
        value.coefficients.length !== 3 ||
        !value.coefficients.every(Number.isSafeInteger) ||
        (index === 0 &&
          (value.expected_points !== player.expected_points ||
            value.coefficients.some((coefficient, at) => coefficient !== player.coefficients[at])))
      )
        return fail();
    }
  }
  return candidate;
}

export const horizonVariable = (family: string, week: number, player?: number) =>
  `${family}${week}${player === undefined ? "" : `_${player}`}`;

/** Exact integer objective, in the same scale as the server's primary objective. */
export function horizonObjective(
  document: DevicePlanDocument,
  inputs: HorizonInputs,
  window: 3 | 5,
): LpTerm[] {
  return inputs.weeks.slice(0, window).flatMap((week, w) => {
    const players = new Map(week.players.map((player) => [player.id, player]));
    return [
      ...document.players.flatMap((player, i) =>
        players
          .get(player.id)!
          .coefficients.map((coefficient, family) =>
            term(
              coefficient * week.discount_weight,
              horizonVariable(["s", "x", "c"][family]!, w, i),
            ),
          ),
      ),
      term(-document.rules.hit_cost_scaled * week.discount_weight, horizonVariable("p", w)),
    ];
  });
}

/** Captain, starters, squad rank sums are the server's three ordered tie-break tiers. */
export function horizonRanks(count: number, window: number, family: "s" | "x" | "c"): LpTerm[] {
  return Array.from({ length: window }, (_, w) =>
    Array.from({ length: count }, (_, i) => term(w * count + i, horizonVariable(family, w, i))),
  ).flat();
}

export function horizonProblem(
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  window: 3 | 5,
): LpProblem {
  const inputs = horizonInputs(document, window);
  const { players, rules } = document;
  const held = new Set(entry.held);
  if (
    held.size !== rules.squad_size ||
    entry.held.some((id) => !players.some((player) => player.id === id)) ||
    !Number.isSafeInteger(entry.bank_tenths) ||
    entry.bank_tenths < 0 ||
    !Number.isSafeInteger(entry.free_transfers) ||
    entry.free_transfers < 0 ||
    entry.free_transfers > rules.max_free_transfers ||
    entry.held.some((id) => !Number.isSafeInteger(entry.sell_tenths[String(id)]))
  )
    return fail();
  const problem: LpProblem = {
    sense: "Maximize",
    objective: horizonObjective(document, inputs, window),
    rows: [],
    binaries: [],
    generals: [],
  };
  const add = (name: string, terms: LpTerm[], sense: "=" | "<=" | ">=", rhs: number) =>
    problem.rows.push(row(name, terms, sense, rhs));
  const ones = (variables: string[]) => variables.map((variable) => term(1, variable));
  const wealth =
    entry.bank_tenths + entry.held.reduce((sum, id) => sum + entry.sell_tenths[id]!, 0);
  const clubs = [...new Set(players.map((player) => player.team))];
  const grandfathered = clubs.some(
    (club) =>
      players.filter((player) => player.team === club && held.has(player.id)).length >
      rules.max_players_per_team,
  );
  for (let w = 0; w < window; w += 1) {
    const v = (family: string, i?: number) => horizonVariable(family, w, i);
    const indices = players.map((_, i) => i);
    const family = (prefix: string) => indices.map((i) => v(prefix, i));
    for (const prefix of ["s", "x", "c", "i", "o"]) problem.binaries.push(...family(prefix));
    problem.binaries.push(v("z"), v("p"), v("k"));
    const cap = rules.max_free_transfers;
    // With at most one move and accrual one, n=min(f-min(m,f)+1,cap)
    // never decreases f. After the first week it is at least one unless
    // cap=0. These reachable-state bounds preserve every integer plan,
    // including FT0's paid first move and the cap=0 boundary. No player,
    // squad or optimum is removed; original player ranks stay unchanged.
    const freeLower = Math.min(cap, Math.max(entry.free_transfers, w > 0 ? 1 : 0));
    problem.generals.push(
      {
        variable: v("f"),
        lower: freeLower,
        upper: Math.min(cap, entry.free_transfers + w),
      },
      { variable: v("u"), lower: 0, upper: cap },
      {
        variable: v("n"),
        lower: Math.min(cap, Math.max(entry.free_transfers, 1)),
        upper: Math.min(cap, entry.free_transfers + w + 1),
      },
    );
    if (freeLower >= 1) add(v("paid_impossible"), [term(1, v("p"))], "=", 0);
    problem.generals.push({ variable: v("m"), lower: 0, upper: 1 });
    problem.generals.push({ variable: v("b"), lower: 0, upper: wealth });
    add(v("size"), ones(family("s")), "=", rules.squad_size);
    add(v("starting"), ones(family("x")), "=", rules.starting_size);
    add(v("captain"), ones(family("c")), "=", 1);
    for (const [position, quota] of Object.entries(rules.squad_position_limits)) {
      const selected = indices.filter((i) => players[i]!.position === position);
      add(v(`quota_${position}`), ones(selected.map((i) => v("s", i))), "=", quota);
      add(
        v(`min_${position}`),
        ones(selected.map((i) => v("x", i))),
        ">=",
        rules.starting_position_min[position]!,
      );
      add(
        v(`max_${position}`),
        ones(selected.map((i) => v("x", i))),
        "<=",
        rules.starting_position_max[position]!,
      );
    }
    for (const [clubIndex, club] of clubs.entries()) {
      const selected = indices.filter((i) => players[i]!.team === club);
      add(
        v(`club_${clubIndex}`),
        [
          ...ones(selected.map((i) => v("s", i))),
          ...(grandfathered ? [term(rules.squad_size - rules.max_players_per_team, v("m"))] : []),
        ],
        "<=",
        grandfathered ? rules.squad_size : rules.max_players_per_team,
      );
    }
    const bank: LpTerm[] = [term(1, v("b"))];
    if (w > 0) bank.push(term(-1, horizonVariable("b", w - 1)));
    players.forEach((player, i) => {
      const original = held.has(player.id);
      const prior = w > 0 ? [term(-1, horizonVariable("s", w - 1, i))] : [];
      add(
        v("continuity", i),
        [term(1, v("s", i)), term(-1, v("i", i)), term(1, v("o", i)), ...prior],
        "=",
        w === 0 && original ? 1 : 0,
      );
      add(v("one_direction", i), [term(1, v("i", i)), term(1, v("o", i))], "<=", 1);
      // Binary continuity and i+o<=1 imply both facets. An arrival is
      // held afterwards and was not held before. They exclude fractional
      // same-week buy/sell cycles from the relaxation, not integer plans.
      add(v("arrival_held", i), [term(1, v("i", i)), term(-1, v("s", i))], "<=", 0);
      add(
        v("arrival_new", i),
        [term(1, v("i", i)), ...(w > 0 ? [term(1, horizonVariable("s", w - 1, i))] : [])],
        "<=",
        w === 0 && original ? 0 : 1,
      );
      add(v("starter_held", i), [term(1, v("x", i)), term(-1, v("s", i))], "<=", 0);
      add(v("captain_starts", i), [term(1, v("c", i)), term(-1, v("x", i))], "<=", 0);
      bank.push(term(player.buy_tenths, v("i", i)), term(-player.buy_tenths, v("o", i)));
      if (original) {
        // An original lot keeps its captured sale basis until its first sale. A
        // repurchase is a new lot at the frozen market price, as on the server.
        problem.binaries.push(v("l", i), v("a", i));
        const previousLot = w > 0 ? [term(-1, horizonVariable("l", w - 1, i))] : [];
        add(
          v("lot", i),
          [term(1, v("l", i)), term(1, v("a", i)), ...previousLot],
          "=",
          w === 0 ? 1 : 0,
        );
        add(v("sale_out", i), [term(1, v("a", i)), term(-1, v("o", i))], "<=", 0);
        add(v("lot_kept", i), [term(1, v("l", i)), term(1, v("o", i))], "<=", 1);
        bank.push(term(player.buy_tenths - entry.sell_tenths[player.id]!, v("a", i)));
      }
    });
    add(v("bank"), bank, "=", w === 0 ? entry.bank_tenths : 0);
    add(
      v("moves"),
      [term(1, v("m")), ...family("i").map((variable) => term(-1, variable))],
      "=",
      0,
    );
    add(
      v("free_before"),
      [term(1, v("f")), ...(w > 0 ? [term(-1, horizonVariable("n", w - 1))] : [])],
      "=",
      w === 0 ? entry.free_transfers : 0,
    );
    add(
      v("free_zero_upper"),
      [term(1, v("f")), term(rules.max_free_transfers, v("z"))],
      "<=",
      rules.max_free_transfers,
    );
    add(v("free_zero_lower"), [term(1, v("f")), term(1, v("z"))], ">=", 1);
    add(v("paid_move"), [term(1, v("p")), term(-1, v("m"))], "<=", 0);
    add(v("paid_zero"), [term(1, v("p")), term(-1, v("z"))], "<=", 0);
    add(v("paid_exact"), [term(1, v("p")), term(-1, v("m")), term(-1, v("z"))], ">=", -1);
    add(
      v("unused"),
      [term(1, v("u")), term(-1, v("f")), term(1, v("m")), term(-1, v("p"))],
      "=",
      0,
    );
    const bound = rules.max_free_transfers + 1;
    // f<=cap and min(m,f)<=1 imply min(f-min(m,f)+1,cap)>=f,
    // even at cap=0. Cut the big-M relaxation's artificial FT decrease.
    add(v("next_monotone"), [term(1, v("n")), term(-1, v("f"))], ">=", 0);
    add(v("next_upper"), [term(1, v("n")), term(-1, v("u"))], "<=", 1);
    add(v("next_lower"), [term(1, v("n")), term(-1, v("u")), term(bound, v("k"))], ">=", 1);
    add(
      v("next_cap"),
      [term(1, v("n")), term(-bound, v("k"))],
      ">=",
      rules.max_free_transfers - bound,
    );
  }
  return problem;
}
