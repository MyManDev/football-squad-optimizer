// Fails the build when the initial JavaScript exceeds the budget (gzip bytes).
//
// "Initial" is what the entry page loads before any route: the module script plus the
// chunks index.html preloads (Vite emits a modulepreload for every static import of the
// entry). Route chunks are lazy by construction and are reported, not budgeted — the
// number a first visit pays is the one the budget guards.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

export const BUDGET_GZIP_BYTES = 150 * 1024;

/** The JavaScript files index.html loads up front, as paths relative to dist/. */
export function initialAssets(html) {
  const files = new Set();
  for (const match of html.matchAll(/<script[^>]+type="module"[^>]+src="([^"]+)"/g)) {
    files.add(match[1]);
  }
  for (const match of html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="([^"]+)"/g)) {
    files.add(match[1]);
  }
  return [...files].filter((name) => name.endsWith(".js")).map((name) => name.replace(/^\//, ""));
}

function gzipBytes(path) {
  return gzipSync(readFileSync(path)).length;
}

function kb(bytes) {
  return (bytes / 1024).toFixed(1);
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\/g, "/"))) {
  const dist = join(process.cwd(), "dist");
  const html = readFileSync(join(dist, "index.html"), "utf8");
  const initial = initialAssets(html).reduce((sum, name) => sum + gzipBytes(join(dist, name)), 0);
  const assets = join(dist, "assets");
  let total = 0;
  for (const name of readdirSync(assets)) {
    const path = join(assets, name);
    if (name.endsWith(".js") && statSync(path).isFile()) total += gzipBytes(path);
  }
  if (initial > BUDGET_GZIP_BYTES) {
    console.error(
      `Initial JavaScript ${kb(initial)} kB gzip exceeds the ${BUDGET_GZIP_BYTES / 1024} kB budget ` +
        `(all chunks: ${kb(total)} kB).`,
    );
    process.exit(1);
  }
  console.log(
    `Initial JavaScript ${kb(initial)} kB gzip (budget ${BUDGET_GZIP_BYTES / 1024} kB); ` +
      `all chunks ${kb(total)} kB.`,
  );
}
