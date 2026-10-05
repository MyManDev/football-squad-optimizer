import { randomBytes } from "node:crypto";
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
// A name no build produces: a missing asset must answer 404, not the shell, and must not
// be cacheable, or an edge keeps HTML for an asset name a later deploy builds. The name is
// new on every run, so a run against a deployment from before assets/404.html poisons only
// a name nothing will ever ask for again. Mirrored by verify_live.py.
export const ABSENT_ASSET_PREFIX = "/assets/smoke-absent-";
export const ABSENT_ASSET = `${ABSENT_ASSET_PREFIX}${randomBytes(4).toString("hex")}.js`;

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
  { path: ABSENT_ASSET, kind: "absent", uncacheable: true },
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
export async function publishedTrees(baseUrl, { fetchImpl, sleep, attempts }) {
  return withAttempts(new URL(DIRECTORY, baseUrl), { sleep, attempts }, async (url) => {
    const response = await fetchImpl(url, request());
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
  });
}

// An asset name inside the shell or a chunk: what the build emits under assets/.
const ASSET_NAME =
  /(?:\/assets\/|["'`]assets\/|\.\/)([A-Za-z0-9_.-]+-[A-Za-z0-9_-]{8}\.(?:js|css|wasm|woff2?))(?![A-Za-z0-9_.-])/g;
const BINARY = /\.(?:wasm|woff2?)$/;
const MAX_ASSETS = 400;

/** Every asset the shell reaches, through the entry and every chunk it names, in turn. */
function assetNames(body) {
  return [...body.matchAll(ASSET_NAME)].map((match) => match[1]);
}

/**
 * Every asset the deployed shell reaches answers as itself: a script, a stylesheet, a font
 * or the solver's wasm, never the HTML shell. A name an edge cached as HTML before it was built
 * is the failure this exists for: the deploy is green and the page is broken there.
 */
/**
 * Every asset the shell reaches answers as itself. While a deployment takes over, the alias
 * can still answer the previous release's shell for a moment, naming assets the new
 * deployment no longer holds (404). So a walk that fails is started again from a freshly read
 * shell, within the same budget, and only a shell that keeps naming a missing asset fails.
 */
export async function checkAssets(baseUrl, { fetchImpl, sleep, attempts }) {
  return retrying({ sleep, attempts }, () => walkAssets(baseUrl, fetchImpl));
}

/** One pass: the shell, then every asset it reaches, each asked once. */
async function walkAssets(baseUrl, fetchImpl) {
  const once = { sleep: async () => {}, attempts: 1 };
  const shell = await withAttempts(new URL("/", baseUrl), once, async (url) => {
    const response = await fetchImpl(url, request());
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.text();
  });
  const seen = new Set();
  let queue = assetNames(shell);
  if (queue.length === 0) throw new Error("the shell names no asset");
  while (queue.length > 0) {
    const batch = [...new Set(queue)].filter((name) => !seen.has(name));
    batch.forEach((name) => seen.add(name));
    if (seen.size > MAX_ASSETS) throw new Error(`more than ${MAX_ASSETS} assets reached`);
    const bodies = await Promise.all(
      batch.map((name) =>
        withAttempts(new URL(`/assets/${name}`, baseUrl), once, async (url) => {
          const response = await fetchImpl(url, request());
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const type = (response.headers.get("content-type") ?? "").toLowerCase();
          if (type.includes("text/html")) throw new Error("an asset answered as the HTML shell");
          if (BINARY.test(name)) return "";
          const body = await response.text();
          if (body.trimStart().toLowerCase().startsWith("<!doctype html")) {
            throw new Error("an asset answered as the HTML shell");
          }
          console.log(`OK ${response.status} ${url}`);
          return body;
        }),
      ),
    );
    queue = bodies.flatMap((body) => assetNames(body));
  }
  return [...seen];
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

function request() {
  return {
    headers: { "cache-control": "no-cache" },
    redirect: "error",
    signal: AbortSignal.timeout(10_000),
  };
}

/** One check, tried up to `attempts` times with a growing pause, as a deploy propagates. */
/** Run `attempt` until it succeeds, backing off between tries; rethrow the last failure. */
async function retrying({ sleep, attempts }, attempt) {
  let lastError;
  for (let tried = 1; tried <= attempts; tried += 1) {
    try {
      return await attempt();
    } catch (error) {
      lastError = error;
      if (tried < attempts) await sleep(Math.min(2 ** tried * 1_000, 15_000));
    }
  }
  throw lastError;
}

async function withAttempts(url, options, check) {
  try {
    return await retrying(options, () => check(url));
  } catch (error) {
    throw new Error(`Deployment smoke failed for ${url}: ${error?.message}`, { cause: error });
  }
}

async function checkEndpoint(baseUrl, check, { fetchImpl, sleep, attempts }) {
  const url = new URL(check.path, baseUrl);
  let lastError;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetchImpl(url, request());
      if (check.kind === "absent") {
        if (response.status !== 404) {
          throw new Error(`an unpublished document answered HTTP ${response.status}`);
        }
        const body = await response.text();
        if (body.includes(SHELL_ELEMENT)) {
          throw new Error("an unpublished document answered with the SPA document");
        }
        if (check.uncacheable) {
          const cacheControl = (response.headers.get("cache-control") ?? "").toLowerCase();
          if (cacheControl.includes("immutable") || /(?:s-)?max-age=[1-9]/.test(cacheControl)) {
            throw new Error(`an absent asset is cacheable: ${cacheControl}`);
          }
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
  const options = { fetchImpl, sleep, attempts };
  const trees = await publishedTrees(baseUrl, options);
  const checks = [...SMOKE_CHECKS, ...trees.flatMap(treeChecks)];
  await Promise.all([
    ...checks.map((check) => checkEndpoint(baseUrl, check, options)),
    checkAssets(baseUrl, options),
  ]);
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
