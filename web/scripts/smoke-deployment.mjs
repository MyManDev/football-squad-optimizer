import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

// The application shell renders into this element. A response that carries it is the shell,
// whatever its status line says, so an absent document must not contain it.
const SHELL_ELEMENT = 'id="root"';

// The site's league directory says which league trees it publishes; a site from before
// the directory answers 404 here and publishes the one legacy tree. Mirrored by
// scripts/release/verify_live.py, and a test holds the two in step.
export const DIRECTORY = "/data/leagues.json";
export const LEGACY_TREE = "league";

export const SMOKE_CHECKS = [
  { path: "/", kind: "html" },
  { path: "/moves", kind: "html" },
  { path: "/rivals", kind: "html" },
  { path: "/league", kind: "html" },
  // A nested client-side route is the first thing a path-scoped not-found rule would break.
  { path: "/league/members/0", kind: "html" },
  { path: "/status", kind: "html" },
  { path: "/fixtures", kind: "html" },
  { path: "/data/index.json", kind: "json", revalidates: true },
];

/** The checks one league tree adds: its member page by number, its members, its absent entry 0. */
export function treeChecks({ leagueId, path }) {
  const checks = [];
  if (leagueId !== null) checks.push({ path: `/league/${leagueId}/members/0`, kind: "html" });
  checks.push({
    path: `/data/${path}/members.json`,
    kind: "json",
    revalidates: true,
    requires: (published) => (published?.payload?.members ?? []).length > 0,
    requirement: "at least one league member",
  });
  // Entry 0 is not an FPL entry, so this document can never be published. Served as the
  // shell with a 200, a publication that never happened is indistinguishable from a corrupt
  // one.
  checks.push({ path: `/data/${path}/entries/0.json`, kind: "absent" });
  return checks;
}

/** The trees the deployment publishes, read from its directory; the legacy tree on a 404. */
export async function publishedTrees(baseUrl, fetchImpl) {
  const response = await fetchImpl(new URL(DIRECTORY, baseUrl), {
    headers: { "cache-control": "no-cache" },
    redirect: "error",
    signal: AbortSignal.timeout(10_000),
  });
  if (response.status === 404) return [{ leagueId: null, path: LEGACY_TREE }];
  if (!response.ok) throw new Error(`the league directory answered HTTP ${response.status}`);
  const document = await response.json();
  const rows = document?.payload?.leagues;
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error("the league directory lists no league");
  }
  return rows.map((row) => {
    if (typeof row?.path !== "string" || !Number.isInteger(row?.league_id)) {
      throw new Error("the league directory has a line that is not a published league");
    }
    return { leagueId: row.league_id, path: row.path };
  });
}

function deploymentUrl(value) {
  const url = new URL(value);
  if (!new Set(["http:", "https:"]).has(url.protocol) || url.username || url.password) {
    throw new Error("Deployment URL must be an HTTP(S) URL without credentials");
  }
  return url;
}

const delay = (milliseconds) =>
  new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));

async function checkEndpoint(baseUrl, check, { fetchImpl, sleep, attempts }) {
  const url = new URL(check.path, baseUrl);
  let lastError;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetchImpl(url, {
        headers: { "cache-control": "no-cache" },
        redirect: "error",
        signal: AbortSignal.timeout(10_000),
      });
      if (check.kind === "absent") {
        if (response.status !== 404) {
          throw new Error(`an unpublished document answered HTTP ${response.status}`);
        }
        const body = await response.text();
        if (body.includes(SHELL_ELEMENT)) {
          throw new Error("an unpublished document answered with the SPA document");
        }
      } else if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      } else if (check.kind === "json") {
        const published = await response.json();
        if (check.requires && !check.requires(published)) {
          throw new Error(`response does not carry ${check.requirement}`);
        }
      } else {
        const body = await response.text();
        if (!body.toLowerCase().includes("<!doctype html")) {
          throw new Error("response is not the SPA document");
        }
      }

      if (check.revalidates) {
        const cacheControl = (response.headers.get("cache-control") ?? "").toLowerCase();
        if (!cacheControl.includes("max-age=0") || !cacheControl.includes("must-revalidate")) {
          throw new Error(`unexpected Cache-Control: ${cacheControl || "<missing>"}`);
        }
      }

      console.log(`OK ${response.status} ${url}`);
      return;
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await sleep(Math.min(2 ** attempt * 1_000, 15_000));
    }
  }

  throw new Error(`Deployment smoke failed for ${url}`, { cause: lastError });
}

export async function smokeDeployment(
  value,
  { fetchImpl = fetch, sleep = delay, attempts = 7 } = {},
) {
  const baseUrl = deploymentUrl(value);
  const trees = await publishedTrees(baseUrl, fetchImpl);
  const checks = [...SMOKE_CHECKS, ...trees.flatMap(treeChecks)];
  await Promise.all(
    checks.map((check) => checkEndpoint(baseUrl, check, { fetchImpl, sleep, attempts })),
  );
}

async function main() {
  const baseUrl = process.argv[2];
  if (!baseUrl) {
    throw new Error("Usage: npm run smoke:deployment -- https://deployment.example");
  }
  await smokeDeployment(baseUrl);
}

const entryPoint = process.argv[1] ? resolve(process.argv[1]) : "";
if (entryPoint === fileURLToPath(import.meta.url)) {
  await main();
}
