// Solve an exported instance with HiGHS in Node and compare with the server's answer.
//   node run_node.mjs <instance.json> [repeats]
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { buildLp, compare, solve } from "./planner.mjs";

const [, , instancePath, repeatsArgument] = process.argv;
const instance = JSON.parse(readFileSync(instancePath, "utf8"));
const require = createRequire(`${process.cwd()}/`);
const loadStarted = performance.now();
const highs = await require("highs")();
const loadSeconds = (performance.now() - loadStarted) / 1000;

const lp = buildLp(instance);
console.log(`players ${instance.players.length}, LP ${(lp.length / 1024).toFixed(0)} KiB, solver load ${loadSeconds.toFixed(2)} s`);
const repeats = Number(repeatsArgument ?? 5);
const timings = [];
let answer;
for (let run = 0; run < repeats; run += 1) {
  answer = solve(highs, instance);
  timings.push(answer.primarySeconds + (answer.tieSeconds ?? 0));
}
const names = new Map(instance.players.map((p) => [p.id, p.name]));
console.log("status", answer.status, "| objective", answer.objectiveValue, "| server", instance.reference.objective_value);
console.log("out:", answer.transfersOut.map((id) => names.get(id)), "in:", answer.transfersIn.map((id) => names.get(id)));
console.log("captain:", names.get(answer.captain));
console.log("same as server:", compare(answer, instance));
console.log("first solve, before the tie-break, same squad/xi/captain:",
  JSON.stringify(answer.firstSolve.squad) === JSON.stringify(instance.reference.squad),
  JSON.stringify(answer.firstSolve.startingXi) === JSON.stringify(instance.reference.starting_xi),
  answer.firstSolve.captain === instance.reference.captain);
const sorted = [...timings].sort((a, b) => a - b);
console.log(`seconds over ${repeats} runs: min ${sorted[0].toFixed(3)}, median ${sorted[Math.floor(repeats / 2)].toFixed(3)}, max ${sorted.at(-1).toFixed(3)} (primary ${answer.primarySeconds.toFixed(3)}, tie-break ${answer.tieSeconds.toFixed(3)}); server CP-SAT ${instance.reference.seconds.toFixed(2)}`);
