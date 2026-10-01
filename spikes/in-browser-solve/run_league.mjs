// Solve every exported instance in a directory and compare three ways: the browser-capable
// solver, the server's solver on the same instance, and the advice the site published.
//   node run_league.mjs <instances dir> <published advice dir>
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { compare, solve } from "./planner.mjs";

const [, , instancesDir, adviceDir] = process.argv;
const require = createRequire(`${process.cwd()}/`);
const highs = await require("highs")();

const rows = [];
for (const file of readdirSync(instancesDir).filter((name) => name.endsWith(".json")).sort()) {
  const instance = JSON.parse(readFileSync(join(instancesDir, file), "utf8"));
  const answer = solve(highs, instance);
  const matches = compare(answer, instance);
  const published = JSON.parse(readFileSync(join(adviceDir, file), "utf8")).payload;
  const publishedIn = published.moves.map((move) => move.player_in.player_id).sort((a, b) => a - b);
  const publishedOut = published.moves.map((move) => move.player_out.player_id).sort((a, b) => a - b);
  rows.push({
    entry: instance.entry_id,
    transfers: answer.transfersIn.length,
    sameAsServerSolver: Object.values(matches).every(Boolean),
    sameAsPublished:
      JSON.stringify(publishedIn) === JSON.stringify(answer.transfersIn) &&
      JSON.stringify(publishedOut) === JSON.stringify(answer.transfersOut) &&
      published.captain.player_id === answer.captain,
    tieBreakMoved:
      JSON.stringify(answer.firstSolve.squad) !== JSON.stringify(answer.squad) ||
      JSON.stringify(answer.firstSolve.startingXi) !== JSON.stringify(answer.startingXi) ||
      answer.firstSolve.captain !== answer.captain,
    browserSolverSeconds: Number((answer.primarySeconds + answer.tieSeconds).toFixed(3)),
    primarySeconds: Number(answer.primarySeconds.toFixed(3)),
    serverSolverSeconds: Number(instance.reference.seconds.toFixed(2)),
    mismatch: Object.entries(matches).filter(([, ok]) => !ok).map(([name]) => name).join(",") || "-",
  });
}
console.table(rows);
const count = (key) => rows.filter((row) => row[key]).length;
const seconds = rows.map((row) => row.browserSolverSeconds).sort((a, b) => a - b);
console.log(`same as the server's solver: ${count("sameAsServerSolver")} of ${rows.length}`);
console.log(`same as the published advice: ${count("sameAsPublished")} of ${rows.length}`);
console.log(`tie-break changed the first answer: ${count("tieBreakMoved")} of ${rows.length}`);
console.log(`browser-capable solver seconds: min ${seconds[0]}, median ${seconds[Math.floor(seconds.length / 2)]}, max ${seconds.at(-1)}`);
