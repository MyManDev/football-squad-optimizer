/** Build the offline schedule probe with the repository's installed web dependencies. */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
const here = dirname(fileURLToPath(import.meta.url));
const dependencies = resolve(process.argv[2] ?? "web/node_modules");
const require = createRequire(resolve(dependencies, "../package.json"));
const { rolldown } = await import(pathToFileURL(require.resolve("rolldown")).href);
const bundle = await rolldown({
  input: resolve(here, "schedule.ts"),
  platform: "node",
  resolve: { modules: [dependencies, "node_modules"] },
});
await bundle.write({ file: resolve(here, "../../..", ".codex-tmp/phase1-schedule.cjs"), format: "cjs" });
await bundle.close();
