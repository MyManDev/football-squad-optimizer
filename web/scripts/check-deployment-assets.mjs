import { lstat, readFile, readdir } from "node:fs/promises";
import { resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

export const MAX_DEPLOYMENT_FILES = 20_000;
export const MAX_DEPLOYMENT_FILE_BYTES = 25 * 1024 * 1024;

const REQUIRED_FILES = ["index.html", "data/index.json", "_headers"];
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
