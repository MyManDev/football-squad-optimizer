import { lstat, readFile, readdir } from "node:fs/promises";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

export const MAX_DEPLOYMENT_FILES = 20_000;
export const MAX_DEPLOYMENT_FILE_BYTES = 25 * 1024 * 1024;

// data/404.html and assets/404.html are required and 404.html is forbidden for the same
// reason. Pages serves the closest 404.html up the directory tree, so the one under data/
// makes an unpublished document answer 404 and the one under assets/ makes a missing asset
// answer 404 (not the shell under a year-long immutable header, which an edge then keeps
// for that name), while the absence of a top-level one keeps every route on the shell.
const REQUIRED_FILES = [
  "index.html",
  "data/index.json",
  "data/404.html",
  "assets/404.html",
  "_headers",
];
const FORBIDDEN_TOP_LEVEL_PATHS = new Set(["404.html", "_worker.js", "functions"]);

function slashPath(root, path) {
  return relative(root, path).replaceAll("\\", "/");
}

export function parseHeaderBlocks(source) {
  const blocks = new Map();
  let route;

  for (const rawLine of source.replaceAll("\r\n", "\n").split("\n")) {
    const line = rawLine.trim();
    if (!line) {
      route = undefined;
      continue;
    }
    if (line.startsWith("#")) continue;

    if (!/^\s/.test(rawLine)) {
      route = line;
      if (!blocks.has(route)) blocks.set(route, new Map());
      continue;
    }
    if (!route) continue;

    const separator = line.indexOf(":");
    if (separator < 1) continue;
    const name = line.slice(0, separator).trim().toLowerCase();
    const value = line.slice(separator + 1).trim();
    const headers = blocks.get(route);
    headers.set(name, [...(headers.get(name) ?? []), value]);
  }

  return blocks;
}

function verifyPublishedDataCacheRule(headersSource) {
  const rules = parseHeaderBlocks(headersSource);
  const cacheValues = rules.get("/data/*")?.get("cache-control") ?? [];
  const tokens = new Set(
    cacheValues.flatMap((value) =>
      value
        .toLowerCase()
        .split(",")
        .map((token) => token.trim()),
    ),
  );
  for (const required of ["public", "max-age=0", "must-revalidate"]) {
    if (!tokens.has(required)) {
      throw new Error(`Deployment artifact /data/* cache rule is missing ${required}`);
    }
  }
}

// The policy every page ships under (ADR 0017): a member's model key is held in the tab, so
// the site runs only its own scripts and sends only to the hosts it names. The build writes
// the compute service's origin into the policy (vite/sitePolicy.ts); a word left in braces
// means the artifact did not come from that build.
const REQUIRED_POLICY = [
  ["script-src", ["'self'", "'wasm-unsafe-eval'"]],
  ["connect-src", ["'self'"]],
  ["object-src", ["'none'"]],
  ["base-uri", ["'none'"]],
  ["frame-ancestors", ["'none'"]],
];

export function verifySiteWidePolicy(headersSource) {
  const policies = parseHeaderBlocks(headersSource).get("/*")?.get("content-security-policy");
  if (!policies || policies.length !== 1) {
    throw new Error("Deployment artifact /* rule must carry exactly one Content-Security-Policy");
  }
  const policy = policies[0];
  if (/[{}]/.test(policy)) {
    throw new Error("Deployment artifact Content-Security-Policy has an unfilled word");
  }
  const directives = new Map(
    policy
      .split(";")
      .map((directive) => directive.trim().split(/\s+/))
      .filter(([name]) => name)
      .map(([name, ...sources]) => [name.toLowerCase(), sources]),
  );
  for (const [name, required] of REQUIRED_POLICY) {
    const sources = directives.get(name) ?? [];
    for (const source of required) {
      if (!sources.includes(source)) {
        throw new Error(`Deployment artifact Content-Security-Policy ${name} lacks ${source}`);
      }
    }
  }
  const scripts = directives.get("script-src") ?? [];
  const allowed = new Set(["'self'", "'wasm-unsafe-eval'"]);
  // Hashes of the site's own inline scripts may join later; no host and no 'unsafe-*' may.
  const extra = scripts.filter(
    (source) => !allowed.has(source) && !/^'sha(256|384|512)-/.test(source),
  );
  if (extra.length > 0) {
    throw new Error(
      `Deployment artifact Content-Security-Policy script-src allows ${extra.join(" ")}`,
    );
  }
  if ((directives.get("connect-src") ?? []).some((source) => /^(https?:|wss?:|\*)$/.test(source))) {
    throw new Error("Deployment artifact Content-Security-Policy connect-src allows any host");
  }
}

export async function inspectDeploymentArtifact(
  directory,
  { maxFiles = MAX_DEPLOYMENT_FILES, maxFileBytes = MAX_DEPLOYMENT_FILE_BYTES } = {},
) {
  const root = resolve(directory);
  const rootStat = await lstat(root);
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) {
    throw new Error("Deployment artifact root must be a real directory");
  }

  let fileCount = 0;
  let totalBytes = 0;

  async function visit(currentDirectory) {
    const entries = await readdir(currentDirectory);
    for (const entry of entries) {
      const path = resolve(currentDirectory, entry);
      const artifactPath = slashPath(root, path);
      const stat = await lstat(path);

      if (stat.isSymbolicLink()) {
        throw new Error(`Deployment artifact contains a symbolic link: ${artifactPath}`);
      }
      if (FORBIDDEN_TOP_LEVEL_PATHS.has(artifactPath)) {
        throw new Error(`Deployment artifact contains forbidden Pages content: ${artifactPath}`);
      }
      if (stat.isDirectory()) {
        await visit(path);
        continue;
      }
      if (!stat.isFile()) {
        throw new Error(`Deployment artifact contains a non-file entry: ${artifactPath}`);
      }

      fileCount += 1;
      totalBytes += stat.size;
      if (fileCount > maxFiles) {
        throw new Error(`Deployment artifact exceeds the ${maxFiles}-file limit`);
      }
      if (stat.size > maxFileBytes) {
        throw new Error(
          `Deployment artifact file exceeds the ${maxFileBytes}-byte limit: ${artifactPath}`,
        );
      }
    }
  }

  await visit(root);

  const contents = new Map();
  for (const requiredPath of REQUIRED_FILES) {
    try {
      contents.set(requiredPath, await readFile(resolve(root, requiredPath), "utf8"));
    } catch (error) {
      throw new Error(`Deployment artifact is missing ${requiredPath}`, { cause: error });
    }
  }

  verifyPublishedDataCacheRule(contents.get("_headers") ?? "");
  verifySiteWidePolicy(contents.get("_headers") ?? "");
  try {
    JSON.parse(contents.get("data/index.json") ?? "");
  } catch (error) {
    throw new Error("Deployment artifact data/index.json is not valid JSON", { cause: error });
  }

  return { fileCount, totalBytes };
}

async function main() {
  const directory = process.argv[2] ?? resolve(import.meta.dirname, "..", "dist");
  const result = await inspectDeploymentArtifact(directory);
  console.log(
    `Deployment artifact accepted: ${result.fileCount} files, ${result.totalBytes} bytes.`,
  );
}

const entryPoint = process.argv[1] ? resolve(process.argv[1]) : "";
if (entryPoint === fileURLToPath(import.meta.url)) {
  await main();
}
