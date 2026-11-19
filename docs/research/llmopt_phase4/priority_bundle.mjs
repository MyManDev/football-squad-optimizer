import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
const require = createRequire(resolve("web/package.json"));
const { rolldown } = await import(
  pathToFileURL(require.resolve("rolldown")).href
);
const bundle = await rolldown({
  input: resolve("docs/research/llmopt_phase4/priority_probe.ts"),
  platform: "node",
});
await bundle.write({
  file: resolve(".codex-tmp/phase4-priority.mjs"),
  format: "esm",
});
await bundle.close();
