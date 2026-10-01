// One member's one-week plan as a mixed-integer program, for a solver that runs in a browser.
//
// Feasibility spike, not product code. It mirrors the one-week model the server builds in
// `src/squadopt/planning/optimizer.py` (`_build_model` with a single week and no chip) and
// `src/squadopt/optimization/decisions.py`, using the server's own integer objective
// coefficients, which the exported instance carries. It runs unchanged in Node and in a page.

// One term a line: LP readers differ on how long a line may be, and none mind short ones.
const PLUS = "\n + ";
const MINUS = "\n - ";

/** The LP text of the primary problem, or of one tie-break tier when `tieBreak` is given. */
export function buildLp(instance, { tieBreak = null } = {}) {
  const { players, held, bank_tenths: bank, free_transfers: freeTransfers, rules } = instance;
  const heldSet = new Set(held);
  const s = (i) => `s${i}`;
  const x = (i) => `x${i}`;
  const c = (i) => `c${i}`;
  const sum = (terms) => (terms.length ? terms.join(PLUS) : "0 s0");

  const objective = [];
  players.forEach((player, i) => {
    const [squad, starter, captain] = player.coefficients;
    if (squad) objective.push(`${squad} ${s(i)}`);
    if (starter) objective.push(`${starter} ${x(i)}`);
    if (captain) objective.push(`${captain} ${c(i)}`);
  });
  const primary = `${objective.join(PLUS)}${MINUS}${rules.hit_cost_scaled} paid`;

  const rows = [];
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
  const clubs = new Map();
  players.forEach((p, i) => clubs.set(p.team, [...(clubs.get(p.team) ?? []), i]));
  [...clubs.values()].forEach((members, k) => {
    rows.push(`club${k}: ${sum(members.map(s))} <= ${rules.max_players_per_team}`);
  });

  // A held player can only leave and anyone else can only arrive, so the squad variable
  // itself is the transfer: arriving is s = 1 off the squad, leaving is s = 0 on it.
  const arrivals = players.map((p, i) => (heldSet.has(p.id) ? -1 : i)).filter((i) => i >= 0);
  const holders = players.map((p, i) => (heldSet.has(p.id) ? i : -1)).filter((i) => i >= 0);
  rows.push(`paid: paid${MINUS}${arrivals.map(s).join(MINUS)} >= ${-freeTransfers}`);
  // bank + sum(sell * (1 - s)) over held - sum(buy * s) over arrivals >= 0
  const proceeds = holders.reduce((total, i) => total + players[i].sell, 0);
  const spend = [
    ...holders.map((i) => `${players[i].sell} ${s(i)}`),
    ...arrivals.map((i) => `${players[i].buy} ${s(i)}`),
  ];
  rows.push(`bank: ${spend.join(PLUS)} <= ${bank + proceeds}`);

  let sense = "Maximize";
  let goal = primary;
  if (tieBreak) {
    // The server's second solve: hold the primary value and minimise a rank sum, so equal
    // plans resolve the same way every time.
    rows.push(`hold: ${primary} = ${tieBreak.primaryValue}`);
    sense = "Minimize";
    goal = rankSum(players, tieBreak.prefix);
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

/** Sum of rank times variable; rank is the player's place in the instance's order. */
function rankSum(players, prefix) {
  return players
    .map((_, i) => `${i} ${prefix}${i}`)
    .filter((_, i) => i > 0)
    .join(PLUS);
}

function selected(solution, players, prefix) {
  return players
    .map((p, i) => (Math.round(solution.Columns[`${prefix}${i}`].Primal) === 1 ? p.id : null))
    .filter((id) => id !== null)
    .sort((a, b) => a - b);
}

const EXACT = { mip_rel_gap: 0, mip_abs_gap: 0, output_flag: false };

/** Solve the primary problem, then the server's three-tier tie-break as three small solves. */
export function solve(highs, instance, now = () => performance.now()) {
  const { players, held } = instance;
  const started = now();
  const first = highs.solve(buildLp(instance), EXACT);
  const primarySeconds = (now() - started) / 1000;
  if (first.Status !== "Optimal") return { status: first.Status, primarySeconds };
  const primaryValue = Math.round(first.ObjectiveValue);

  // Captain rank decides first, then the starters' rank sum, then the squad's. One solve
  // per tier keeps every coefficient small instead of packing three tiers into one row.
  const tieStarted = now();
  const fixed = [];
  let last = first;
  for (const prefix of ["c", "x", "s"]) {
    const tier = highs.solve(buildLp(instance, { tieBreak: { primaryValue, prefix, fixed } }), EXACT);
    if (tier.Status !== "Optimal") return { status: `tie-break ${tier.Status}`, primarySeconds };
    fixed.push(`${rankSum(players, prefix)} = ${Math.round(tier.ObjectiveValue)}`);
    last = tier;
  }
  const tieSeconds = (now() - tieStarted) / 1000;

  const heldSet = new Set(held);
  const squad = selected(last, players, "s");
  return {
    status: "Optimal",
    primaryValue,
    objectiveValue: primaryValue / instance.rules.expected_points_scale,
    primarySeconds,
    tieSeconds,
    squad,
    startingXi: selected(last, players, "x"),
    captain: selected(last, players, "c")[0],
    transfersIn: squad.filter((id) => !heldSet.has(id)),
    transfersOut: held.filter((id) => !squad.includes(id)).sort((a, b) => a - b),
    firstSolve: {
      squad: selected(first, players, "s"),
      startingXi: selected(first, players, "x"),
      captain: selected(first, players, "c")[0],
    },
  };
}

/** The server's integer objective for a selection, from the same scaled coefficients. */
export function scaledObjective(instance, selection) {
  const byId = new Map(instance.players.map((player) => [player.id, player.coefficients]));
  const total = (ids, column) => ids.reduce((sum, id) => sum + byId.get(id)[column], 0);
  const paid = Math.max(0, selection.transfers_in.length - instance.free_transfers);
  return (
    total(selection.squad, 0) +
    total(selection.starting_xi, 1) +
    byId.get(selection.captain)[2] -
    instance.rules.hit_cost_scaled * paid
  );
}

/** Compare a browser-side answer with the server's reference, field by field. */
export function compare(answer, instance) {
  const { reference } = instance;
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  return {
    // Integer against integer: the server reports its objective unscaled and as a float.
    objective: answer.primaryValue === scaledObjective(instance, reference),
    squad: same(answer.squad, reference.squad),
    startingXi: same(answer.startingXi, reference.starting_xi),
    captain: answer.captain === reference.captain,
    transfersIn: same(answer.transfersIn, reference.transfers_in),
    transfersOut: same(answer.transfersOut, reference.transfers_out),
  };
}
