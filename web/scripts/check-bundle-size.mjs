// Fails the build when the initial JavaScript exceeds the budget (gzip bytes).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const BUDGET_GZIP_BYTES = 150 * 1024;
const dir = join(process.cwd(), "dist", "assets");
let total = 0;
for (const name of readdirSync(dir)) {
  if (!name.endsWith(".js")) continue;
  const path = join(dir, name);
  if (!statSync(path).isFile()) continue;
  total += gzipSync(readFileSync(path)).length;
}
const kb = (total / 1024).toFixed(1);
if (total > BUDGET_GZIP_BYTES) {
  console.error(
    `JavaScript bundle ${kb} kB gzip exceeds the ${BUDGET_GZIP_BYTES / 1024} kB budget.`,
  );
  process.exit(1);
}
console.log(`JavaScript bundle ${kb} kB gzip (budget ${BUDGET_GZIP_BYTES / 1024} kB).`);
