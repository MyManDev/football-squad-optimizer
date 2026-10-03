/**
 * One member's one-week plan as a mixed-integer program, for a solver on the member's
 * own device.
 *
 * It restates the one-week model the server builds (`squadopt/planning/optimizer.py`,
 * one week, with or without a chip played that week) over the numbers the server
 * publishes for exactly that purpose
 * (`squadopt/application/device_plan.py`): the table in the solver's order, the server's
 * integer objective coefficients, and the rules as numbers. The server's deterministic
 * tie-break is reproduced as three small follow-up solves. A parity test holds this
 * model to the server's answers on fixed instances; the LP text here is the whole model.
 */

import type {
  DeviceChip,
  DevicePlanAnswer,
  DevicePlanDocument,
  DevicePlanEntry,
  DevicePlanMove,
  DevicePlanPlayer,
} from "./types";

/** The one-shot solver this model needs: HiGHS's legacy `solve` over LP text. */
export interface LpSolver {
  solve(
    problem: string,
    options?: Record<string, unknown>,
  ): {
    Status: string;
    ObjectiveValue: number;
    Columns: Record<string, { Primal: number }>;
  };
}

// One term a line: LP readers differ on how long a line may be, and none mind short ones.
const PLUS = "\n + ";
const MINUS = "\n - ";

const EXACT = { mip_rel_gap: 0, mip_abs_gap: 0, output_flag: false };

interface TieBreak {
  primaryValue: number;
  prefix: "c" | "x" | "s";
  fixed: string[];
}

interface BuildOptions {
  tieBreak?: TieBreak | null;
  chip?: DeviceChip | null;
}

/**
 * A chip's objective, from the planner's own model: a Bench Boost scores every squad
 * member in full (the starter coefficient moves from the eleven to the fifteen), a Triple
 * Captain counts the captain's coefficient once more, and a Wildcard or a Free Hit lifts
 * the hits and the cap and scores as any week does. The planner's remainder for the bench
 * is a non-negative coefficient; a document that carries a negative one is refused rather
 * than scored on a model the planner does not use.
 */
function chipCoefficients(
  player: DevicePlanPlayer,
  chip: DeviceChip | null,
): [number, number, number] {
  const [squad, starter, captain] = player.coefficients;
  if (chip === "bboost") {
    if (starter < 0) throw new DevicePlanRefused("negative starter coefficient", "plan");
    return [squad + starter, 0, captain];
  }
  if (chip === "3xc") return [squad, starter, 2 * captain];
  return [squad, starter, captain];
}

/** Sum of rank times variable; rank is the player's place in the document's order. */
function rankSum(count: number, prefix: string): string {
  const terms: string[] = [];
  for (let i = 1; i < count; i += 1) terms.push(`${i} ${prefix}${i}`);
  return terms.join(PLUS);
}

/** The LP text of the primary problem, of one tie-break tier, or of the hold problem. */
export function buildLp(
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  { tieBreak = null, chip = null }: BuildOptions = {},
): string {
  const { players, rules } = document;
  const heldSet = new Set(entry.held);
  const s = (i: number) => `s${i}`;
  const x = (i: number) => `x${i}`;
  const c = (i: number) => `c${i}`;
  const sum = (terms: string[]) => (terms.length ? terms.join(PLUS) : "0 s0");

  const objective: string[] = [];
  players.forEach((player, i) => {
    const [squad, starter, captain] = chipCoefficients(player, chip);
    if (squad) objective.push(`${squad} ${s(i)}`);
    if (starter) objective.push(`${starter} ${x(i)}`);
    if (captain) objective.push(`${captain} ${c(i)}`);
  });
  // A rebuild week pays no hits, so the paid transfers leave the objective.
  const primary = rebuilds(chip)
    ? objective.join(PLUS)
    : `${objective.join(PLUS)}${MINUS}${rules.hit_cost_scaled} paid`;

  const rows: string[] = [];
  rows.push(`squad: ${sum(players.map((_, i) => s(i)))} = ${rules.squad_size}`);
  rows.push(`xi: ${sum(players.map((_, i) => x(i)))} = ${rules.starting_size}`);
  rows.push(`cap: ${sum(players.map((_, i) => c(i)))} = 1`);
  players.forEach((_, i) => {
    rows.push(`st${i}: ${x(i)} - ${s(i)} <= 0`);
    rows.push(`ca${i}: ${c(i)} - ${x(i)} <= 0`);
  });
  for (const position of Object.keys(rules.squad_position_limits)) {
    const members = players.map((p, i) => (p.position === position ? i : -1)).filter((i) => i >= 0);
    rows.push(`sq_${position}: ${sum(members.map(s))} = ${rules.squad_position_limits[position]}`);
    rows.push(`lo_${position}: ${sum(members.map(x))} >= ${rules.starting_position_min[position]}`);
    rows.push(`hi_${position}: ${sum(members.map(x))} <= ${rules.starting_position_max[position]}`);
  }
  const clubs = new Map<string, number[]>();
  players.forEach((p, i) => clubs.set(p.team, [...(clubs.get(p.team) ?? []), i]));
  [...clubs.values()].forEach((members, k) => {
    rows.push(`club${k}: ${sum(members.map(s))} <= ${rules.max_players_per_team}`);
  });

  // A held player can only leave and anyone else can only arrive, so the squad variable
  // itself is the transfer: arriving is s = 1 off the squad, leaving is s = 0 on it.
  const arrivals = players.map((p, i) => (heldSet.has(p.id) ? -1 : i)).filter((i) => i >= 0);
  const holders = players.map((p, i) => (heldSet.has(p.id) ? i : -1)).filter((i) => i >= 0);
  rows.push(`paid: paid${MINUS}${arrivals.map(s).join(MINUS)} >= ${-entry.free_transfers}`);
  // bank + sum(sell * (1 - s)) over held - sum(buy * s) over arrivals >= 0
  const sell = (i: number) => entry.sell_tenths[String(players[i]!.id)] ?? players[i]!.buy_tenths;
  const proceeds = holders.reduce((total, i) => total + sell(i), 0);
  const spend = [
    ...holders.map((i) => `${sell(i)} ${s(i)}`),
    ...arrivals.map((i) => `${players[i]!.buy_tenths} ${s(i)}`),
  ];
  rows.push(`bank: ${spend.join(PLUS)} <= ${entry.bank_tenths + proceeds}`);

  let sense = "Maximize";
  let goal = primary;
  if (tieBreak) {
    // The server's second solve: hold the primary value and minimise a rank sum, so equal
    // plans resolve the same way every time.
    rows.push(`hold: ${primary} = ${tieBreak.primaryValue}`);
    sense = "Minimize";
    goal = rankSum(players.length, tieBreak.prefix);
    tieBreak.fixed.forEach((row, k) => rows.push(`fix${k}: ${row}`));
  }

  const binaries = players.flatMap((_, i) => [s(i), x(i), c(i)]);
  return [
    sense,
    ` obj: ${goal}`,
    "Subject To",
    ...rows.map((row) => ` ${row}`),
    "Bounds",
    ` 0 <= paid <= ${rules.squad_size}`,
    "General",
    " paid",
    "Binary",
    ...binaries.map((name) => ` ${name}`),
    "End",
  ].join("\n");
}

/**
 * The lineup problem alone, for a fifteen taken as given: the eleven and the captain on
 * the server's objective, under the eleven's position bounds. The squad's own rules (the
 * club limit, the bank, the transfer line) do not bind a fifteen that is not being
 * chosen, exactly as the server's `best_eleven_points` reads a fifteen's worth.
 */
export function buildLineupLp(
  document: DevicePlanDocument,
  squad: number[],
  chip: DeviceChip | null = null,
): string {
  const { players, rules } = document;
  const inSquad = new Set(squad);
  const x = (i: number) => `x${i}`;
  const c = (i: number) => `c${i}`;
  const chosen = players.map((p, i) => (inSquad.has(p.id) ? i : -1)).filter((i) => i >= 0);
  const sum = (terms: string[]) => (terms.length ? terms.join(PLUS) : "0 x0");
  const objective: string[] = [];
  for (const i of chosen) {
    const [, starter, captain] = chipCoefficients(players[i]!, chip);
    if (starter) objective.push(`${starter} ${x(i)}`);
    if (captain) objective.push(`${captain} ${c(i)}`);
  }
  const rows: string[] = [];
  rows.push(`xi: ${sum(chosen.map(x))} = ${rules.starting_size}`);
  rows.push(`cap: ${sum(chosen.map(c))} = 1`);
  for (const i of chosen) rows.push(`ca${i}: ${c(i)} - ${x(i)} <= 0`);
  for (const position of Object.keys(rules.squad_position_limits)) {
    const members = chosen.filter((i) => players[i]!.position === position);
    rows.push(`lo_${position}: ${sum(members.map(x))} >= ${rules.starting_position_min[position]}`);
    rows.push(`hi_${position}: ${sum(members.map(x))} <= ${rules.starting_position_max[position]}`);
  }
  return [
    "Maximize",
    // Under a Bench Boost the fifteen's points are a constant and only the captain is
    // chosen; the eleven is then whichever the solver names, which is what it is for.
    ` obj: ${objective.length ? objective.join(PLUS) : "0 x0"}`,
    "Subject To",
    ...rows.map((row) => ` ${row}`),
    "Binary",
    ...chosen.flatMap((i) => [` ${x(i)}`, ` ${c(i)}`]),
    "End",
  ].join("\n");
}

type Solution = ReturnType<LpSolver["solve"]>;

function selected(solution: Solution, document: DevicePlanDocument, prefix: string): number[] {
  return document.players
    .map((p, i) => (Math.round(solution.Columns[`${prefix}${i}`]?.Primal ?? 0) === 1 ? p.id : null))
    .filter((id): id is number => id !== null)
    .sort((a, b) => a - b);
}

/**
 * What a week scores on the document's own expected points: the eleven with the captain
 * doubled; tripled under a Triple Captain; every one of the fifteen under a Bench Boost.
 */
function weekPoints(
  document: DevicePlanDocument,
  squad: number[],
  startingXi: number[],
  captain: number,
  chip: DeviceChip | null,
): number {
  const points = new Map(document.players.map((p) => [p.id, p.expected_points]));
  let total = 0;
  for (const id of chip === "bboost" ? squad : startingXi) total += points.get(id) ?? 0;
  return total + (chip === "3xc" ? 2 : 1) * (points.get(captain) ?? 0);
}

export class DevicePlanRefused extends Error {
  readonly status: string;
  readonly stage: "plan" | "tie-break" | "hold";

  constructor(status: string, stage: "plan" | "tie-break" | "hold") {
    super(`The device solve did not prove a plan (${stage}: ${status}).`);
    this.name = "DevicePlanRefused";
    this.status = status;
    this.stage = stage;
  }
}

/**
 * Solve the primary problem, the server's three-tier tie-break, and the hold problem.
 *
 * Throws `DevicePlanRefused` when any solve ends other than optimal: a plan that was not
 * proved is not shown.
 */
export function solvePlan(
  solver: LpSolver,
  published: DevicePlanDocument,
  entry: DevicePlanEntry,
  now: () => number = () => performance.now(),
  chip: DeviceChip | null = null,
): DevicePlanAnswer {
  const started = now();
  // The planner sorts its table by id before it solves and ranks ties in that order;
  // the device does the same whatever order the document arrived in.
  const document: DevicePlanDocument = {
    ...published,
    players: [...published.players].sort((a, b) => a.id - b.id),
  };
  const first = solver.solve(buildLp(document, entry, { chip }), EXACT);
  if (first.Status !== "Optimal") throw new DevicePlanRefused(first.Status, "plan");
  const primaryValue = Math.round(first.ObjectiveValue);

  // Captain rank decides first, then the starters' rank sum, then the squad's. One solve
  // per tier keeps every coefficient small instead of packing three tiers into one row.
  const fixed: string[] = [];
  let last = first;
  for (const prefix of ["c", "x", "s"] as const) {
    const tier = solver.solve(
      buildLp(document, entry, { tieBreak: { primaryValue, prefix, fixed }, chip }),
      EXACT,
    );
    if (tier.Status !== "Optimal") throw new DevicePlanRefused(tier.Status, "tie-break");
    fixed.push(`${rankSum(document.players.length, prefix)} = ${Math.round(tier.ObjectiveValue)}`);
    last = tier;
  }

  // The value of fielding exactly a fifteen: its best eleven and captain on the same
  // objective, the basis every gain is on.
  const valueOf = (squad: number[]): number => {
    const fixed = solver.solve(buildLineupLp(document, squad, chip), EXACT);
    if (fixed.Status !== "Optimal") throw new DevicePlanRefused(fixed.Status, "hold");
    return weekPoints(
      document,
      squad,
      selected(fixed, document, "x"),
      selected(fixed, document, "c")[0]!,
      chip,
    );
  };

  const heldSet = new Set(entry.held);
  const squad = selected(last, document, "s");
  const startingXi = selected(last, document, "x");
  const captain = selected(last, document, "c")[0]!;
  const transfersIn = squad.filter((id) => !heldSet.has(id));
  const transfersOut = entry.held.filter((id) => !squad.includes(id)).sort((a, b) => a - b);
  const paid = rebuilds(chip) ? 0 : Math.max(0, transfersIn.length - entry.free_transfers);
  const expectedOwnPoints = weekPoints(document, squad, startingXi, captain, chip);
  const holdPoints = valueOf(entry.held);
  const { moves, gain } = attributedMoves(
    document,
    entry.held,
    transfersOut,
    transfersIn,
    holdPoints,
    expectedOwnPoints,
    valueOf,
  );
  return {
    objective_scaled: primaryValue,
    objective: primaryValue / document.rules.expected_points_scale,
    squad,
    starting_xi: startingXi,
    captain,
    vice_captain: viceCaptain(document, startingXi, captain),
    bench: orderedBench(document, squad, startingXi),
    transfers_in: transfersIn,
    transfers_out: transfersOut,
    transfer_hit_points: paid * document.rules.hit_points_charged,
    expected_own_points: expectedOwnPoints,
    hold_points: holdPoints,
    moves,
    expected_gain_vs_hold: gain,
    chip,
    seconds: (now() - started) / 1000,
  };
}

/** A Wildcard or a Free Hit: unlimited transfers, none of them paid. */
export function rebuilds(chip: DeviceChip | null): boolean {
  return chip === "wildcard" || chip === "freehit";
}

/**
 * A chip week beside the member's own no-chip plan: what the chip week scores minus its
 * hits, less the same for the plan without it. The server's `gain_vs_no_chip`, from the
 * two plans the device solved.
 */
export function gainVsNoChip(withChip: DevicePlanAnswer, without: DevicePlanAnswer): number {
  return (
    withChip.expected_own_points -
    withChip.transfer_hit_points -
    (without.expected_own_points - without.transfer_hit_points)
  );
}

/**
 * The server's pairing: each outgoing player with an incoming player of the same
 * position, both lists in id order; whatever is left over is paired in id order at the
 * end rather than dropped.
 */
export function pairedByPosition(
  document: DevicePlanDocument,
  outs: number[],
  ins: number[],
): Array<[number | null, number | null]> {
  const position = new Map(document.players.map((p) => [p.id, p.position]));
  const waiting = new Map<string, number[]>();
  const spareIns: number[] = [];
  for (const arriving of ins) {
    const where = position.get(arriving);
    if (where === undefined) spareIns.push(arriving);
    else waiting.set(where, [...(waiting.get(where) ?? []), arriving]);
  }
  const pairs: Array<[number | null, number | null]> = [];
  const spareOuts: number[] = [];
  for (const leaving of outs) {
    const where = position.get(leaving);
    const queue = where === undefined ? undefined : waiting.get(where);
    if (queue && queue.length) pairs.push([leaving, queue.shift()!]);
    else spareOuts.push(leaving);
  }
  const leftoverIns = [...[...waiting.values()].flat(), ...spareIns].sort((a, b) => a - b);
  for (let index = 0; index < Math.max(spareOuts.length, leftoverIns.length); index += 1) {
    pairs.push([spareOuts[index] ?? null, leftoverIns[index] ?? null]);
  }
  return pairs;
}

/**
 * Each swap's share of the gain: the rows are applied to the held fifteen in order and
 * the basis re-read after each. Null on every row, and no total, when the chain does
 * not end at the eleven the plan fields.
 */
function attributedMoves(
  document: DevicePlanDocument,
  held: number[],
  outs: number[],
  ins: number[],
  holdPoints: number,
  expectedOwnPoints: number,
  valueOf: (squad: number[]) => number,
): { moves: DevicePlanMove[]; gain: number | null } {
  const pairs = pairedByPosition(document, outs, ins);
  const squad = [...held];
  const gains: number[] = [];
  let previous = holdPoints;
  let walkable = true;
  for (const [leaving, arriving] of pairs) {
    if (!walkable) break;
    if (
      leaving === null ||
      arriving === null ||
      !squad.includes(leaving) ||
      squad.includes(arriving)
    ) {
      walkable = false;
      break;
    }
    squad[squad.indexOf(leaving)] = arriving;
    const value = valueOf(squad);
    gains.push(value - previous);
    previous = value;
  }
  if (!walkable || Math.abs(previous - expectedOwnPoints) > 1e-6) {
    return {
      moves: pairs.map(([out, arriving]) => ({ out, in: arriving, gain: null })),
      gain: null,
    };
  }
  return {
    moves: pairs.map(([out, arriving], index) => ({
      out,
      in: arriving,
      gain: gains[index] ?? null,
    })),
    gain: gains.reduce((total, value) => total + value, 0),
  };
}

/** The server's completion rule: the eleven's next-highest points, the lower id on a tie. */
export function viceCaptain(
  document: DevicePlanDocument,
  startingXi: number[],
  captain: number,
): number {
  const points = new Map(document.players.map((p) => [p.id, p.expected_points]));
  const eligible = startingXi.filter((id) => id !== captain);
  eligible.sort((a, b) => (points.get(b) ?? 0) - (points.get(a) ?? 0) || a - b);
  return eligible[0]!;
}

/**
 * The bench in the order the game walks it: the goalkeeper first, then outfield by
 * descending expected points, the document's order on a tie. The server's shared bench
 * rule orders by points per appearance chance where every row carries one and falls
 * back to points otherwise; the one-week member path's table carries no chance, so the
 * fallback is what the server publishes for this plan.
 */
export function orderedBench(
  document: DevicePlanDocument,
  squad: number[],
  startingXi: number[],
): number[] {
  const starters = new Set(startingXi);
  const rows = document.players.filter((p) => squad.includes(p.id) && !starters.has(p.id));
  const keepers = rows.filter((p) => p.position === "GK").map((p) => p.id);
  const outfield = rows
    .map((p, order) => ({ p, order }))
    .filter(({ p }) => p.position !== "GK")
    .sort((a, b) => b.p.expected_points - a.p.expected_points || a.order - b.order)
    .map(({ p }) => p.id);
  return [...keepers, ...outfield];
}
