/**
 * One member's one-week plan as a mixed-integer program, for a solver on the member's
 * own device.
 *
 * It restates the one-week model the server builds (`squadopt/planning/optimizer.py`,
 * one week, no chip) over the numbers the server publishes for exactly that purpose
 * (`squadopt/application/device_plan.py`): the table in the solver's order, the server's
 * integer objective coefficients, and the rules as numbers. The server's deterministic
 * tie-break is reproduced as three small follow-up solves. A parity test holds this
 * model to the server's answers on fixed instances; the LP text here is the whole model.
 */

import type { DevicePlanAnswer, DevicePlanDocument, DevicePlanEntry } from "./types";

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
  /** Fix the squad to the held fifteen: the value of doing nothing. */
  hold?: boolean;
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
  { tieBreak = null, hold = false }: BuildOptions = {},
): string {
  const { players, rules } = document;
  const heldSet = new Set(entry.held);
  const s = (i: number) => `s${i}`;
  const x = (i: number) => `x${i}`;
  const c = (i: number) => `c${i}`;
  const sum = (terms: string[]) => (terms.length ? terms.join(PLUS) : "0 s0");

  const objective: string[] = [];
  players.forEach((player, i) => {
    const [squad, starter, captain] = player.coefficients;
    if (squad) objective.push(`${squad} ${s(i)}`);
    if (starter) objective.push(`${starter} ${x(i)}`);
    if (captain) objective.push(`${captain} ${c(i)}`);
  });
  const primary = `${objective.join(PLUS)}${MINUS}${rules.hit_cost_scaled} paid`;

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
  if (hold) holders.forEach((i, k) => rows.push(`keep${k}: ${s(i)} = 1`));

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

type Solution = ReturnType<LpSolver["solve"]>;

function selected(solution: Solution, document: DevicePlanDocument, prefix: string): number[] {
  return document.players
    .map((p, i) => (Math.round(solution.Columns[`${prefix}${i}`]?.Primal ?? 0) === 1 ? p.id : null))
    .filter((id): id is number => id !== null)
    .sort((a, b) => a - b);
}

/** The eleven with the captain doubled, on the document's own expected points. */
function elevenPoints(document: DevicePlanDocument, startingXi: number[], captain: number): number {
  const points = new Map(document.players.map((p) => [p.id, p.expected_points]));
  let total = 0;
  for (const id of startingXi) total += points.get(id) ?? 0;
  return total + (points.get(captain) ?? 0);
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
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  now: () => number = () => performance.now(),
): DevicePlanAnswer {
  const started = now();
  const first = solver.solve(buildLp(document, entry), EXACT);
  if (first.Status !== "Optimal") throw new DevicePlanRefused(first.Status, "plan");
  const primaryValue = Math.round(first.ObjectiveValue);

  // Captain rank decides first, then the starters' rank sum, then the squad's. One solve
  // per tier keeps every coefficient small instead of packing three tiers into one row.
  const fixed: string[] = [];
  let last = first;
  for (const prefix of ["c", "x", "s"] as const) {
    const tier = solver.solve(
      buildLp(document, entry, { tieBreak: { primaryValue, prefix, fixed } }),
      EXACT,
    );
    if (tier.Status !== "Optimal") throw new DevicePlanRefused(tier.Status, "tie-break");
    fixed.push(`${rankSum(document.players.length, prefix)} = ${Math.round(tier.ObjectiveValue)}`);
    last = tier;
  }

  // Doing nothing: the held fifteen's best eleven and captain, the basis the gain is on.
  const held = solver.solve(buildLp(document, entry, { hold: true }), EXACT);
  if (held.Status !== "Optimal") throw new DevicePlanRefused(held.Status, "hold");

  const heldSet = new Set(entry.held);
  const squad = selected(last, document, "s");
  const startingXi = selected(last, document, "x");
  const captain = selected(last, document, "c")[0]!;
  const transfersIn = squad.filter((id) => !heldSet.has(id));
  const paid = Math.max(0, transfersIn.length - entry.free_transfers);
  const holdXi = selected(held, document, "x");
  const holdCaptain = selected(held, document, "c")[0]!;
  return {
    objective_scaled: primaryValue,
    objective: primaryValue / document.rules.expected_points_scale,
    squad,
    starting_xi: startingXi,
    captain,
    vice_captain: viceCaptain(document, startingXi, captain),
    bench: orderedBench(document, squad, startingXi),
    transfers_in: transfersIn,
    transfers_out: entry.held.filter((id) => !squad.includes(id)).sort((a, b) => a - b),
    transfer_hit_points: paid * document.rules.hit_points_charged,
    expected_own_points: elevenPoints(document, startingXi, captain),
    hold_points: elevenPoints(document, holdXi, holdCaptain),
    seconds: (now() - started) / 1000,
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
 * descending expected points, the document's order on a tie.
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
