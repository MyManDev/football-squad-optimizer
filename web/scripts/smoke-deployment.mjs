import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const SMOKE_CHECKS = [
  { path: "/", kind: "html" },
  { path: "/moves", kind: "html" },
  { path: "/rivals", kind: "html" },
  { path: "/league", kind: "html" },
  { path: "/analysis", kind: "html" },
  { path: "/status", kind: "html" },
  { path: "/data/index.json", kind: "json", revalidates: true },
];

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
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      if (check.kind === "json") {
        await response.json();
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
  await Promise.all(
    SMOKE_CHECKS.map((check) => checkEndpoint(baseUrl, check, { fetchImpl, sleep, attempts })),
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
