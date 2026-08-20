import { access, readFile } from "node:fs/promises";
import { resolve } from "node:path";

const dist = resolve(import.meta.dirname, "..", "dist");

const requiredFiles = ["index.html", "data/index.json", "_headers"];
const contents = new Map();

for (const relativePath of requiredFiles) {
  try {
    contents.set(relativePath, await readFile(resolve(dist, relativePath), "utf8"));
  } catch (error) {
    throw new Error(`Deployment artifact is missing ${relativePath}`, { cause: error });
  }
}

let hasTopLevel404 = true;
try {
  await access(resolve(dist, "404.html"));
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
  hasTopLevel404 = false;
}

if (hasTopLevel404) {
  throw new Error("A top-level 404.html disables Cloudflare Pages' SPA fallback");
}

const headers = contents.get("_headers") ?? "";
if (!headers.includes("/data/*") || !headers.includes("max-age=0, must-revalidate")) {
  throw new Error("Deployment artifact does not contain the published-data cache rule");
}

JSON.parse(contents.get("data/index.json") ?? "");
console.log(`Deployment artifact contains ${requiredFiles.length} required files.`);
