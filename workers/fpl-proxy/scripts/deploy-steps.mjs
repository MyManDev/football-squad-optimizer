// The steps of .github/workflows/deploy-fpl-proxy.yml that read better, and can be tested, as
// JavaScript rather than shell: smoke the deployed forwarder and confirm a deleted one is gone.
// Both ask one path under the route that is none of the three routes, so neither asks FPL
// anything. Run as `node workers/fpl-proxy/scripts/deploy-steps.mjs <step>` from the repository
// root. It reads no credential: wrangler-action holds those.

import { appendFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

import { MARKER_HEADER, MARKER_VALUE, SITE_ORIGIN } from "../src/proxy.js";

/** Under the route, and none of its three paths: the Worker answers it with its JSON 404. */
export const SMOKE_URL = `${SITE_ORIGIN}/api/v1/fpl/smoke`;

async function readAnswer(fetchImpl, url, timeoutMs) {
  try {
    const response = await fetchImpl(url, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
    });
    const text = await response.text();
    const contentType = response.headers.get("content-type") ?? "";
    const marked = response.headers.get(MARKER_HEADER) === MARKER_VALUE;
    let body = null;
    if (contentType.includes("application/json")) {
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
    }
    return { status: response.status, contentType, body, marked };
  } catch (error) {
    return {
      status: null,
      contentType: "",
      body: null,
      marked: false,
      error: `${error.name}: ${error.message}`,
    };
  }
}

/**
 * Whether an answer is the forwarder's own 404: JSON, marked with its header, saying not_found.
 * The site's HTML shell, which answers the path while the route has not reached the edge, is
 * not; nor is Cloudflare's own error page.
 */
export function isForwarderNotFound(answer) {
  return (
    answer.status === 404 &&
    answer.marked &&
    answer.contentType.includes("application/json") &&
    answer.body?.error === "not_found"
  );
}

/**
 * Whether an answer shows the forwarder gone: an HTTP answer without the Worker's marker
 * header, such as the site's own page. No answer at all, any answer the Worker marked, and
 * Cloudflare's own 429 or 5xx in front of it prove nothing.
 */
export function showsGone(answer) {
  if (answer.status === null || answer.marked) return false;
  return answer.status !== 429 && answer.status < 500;
}

function described(answer) {
  if (answer.status === null) return `no answer (${answer.error})`;
  return `HTTP ${answer.status} ${answer.contentType || "without a content type"}`;
}

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Ask the smoke path until the Worker answers it, a few times while a new route spreads. */
export async function smoke({
  fetchImpl = fetch,
  attempts = 6,
  waitMs = 10_000,
  timeoutMs = 20_000,
  sleep = pause,
  log = console.log,
} = {}) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const answer = await readAnswer(fetchImpl, SMOKE_URL, timeoutMs);
    if (isForwarderNotFound(answer)) return { ok: true, answer };
    log(`attempt ${attempt} of ${attempts}: ${described(answer)}, not the forwarder's 404 yet`);
    if (attempt < attempts) await sleep(waitMs);
  }
  return { ok: false, answer: null };
}

/** After a Worker delete: the smoke path must stop answering as the Worker. */
export async function confirmGone({
  fetchImpl = fetch,
  attempts = 6,
  waitMs = 10_000,
  timeoutMs = 20_000,
  sleep = pause,
  log = console.log,
} = {}) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const answer = await readAnswer(fetchImpl, SMOKE_URL, timeoutMs);
    if (showsGone(answer)) return true;
    const seen = answer.marked
      ? `the Worker still answers (HTTP ${answer.status})`
      : described(answer);
    log(`attempt ${attempt} of ${attempts}: ${seen}`);
    if (attempt < attempts) await sleep(waitMs);
  }
  return false;
}

async function writeSummary(markdown) {
  if (process.env.GITHUB_STEP_SUMMARY) {
    await appendFile(process.env.GITHUB_STEP_SUMMARY, `${markdown}\n`);
  }
}

async function main(step) {
  if (step === "smoke") {
    const { ok, answer } = await smoke();
    if (!ok) {
      console.log(`::error::The forwarder did not answer ${SMOKE_URL} with its JSON 404.`);
      return 1;
    }
    console.log(JSON.stringify(answer.body));
    await writeSummary(
      `## FPL forwarder answers\n\n${SMOKE_URL} answered HTTP 404 JSON with ` +
        `\`${MARKER_HEADER}: ${MARKER_VALUE}\`.`,
    );
    return 0;
  }
  if (step === "confirm-gone") {
    if (await confirmGone()) {
      console.log(`${SMOKE_URL} no longer answers as the forwarder`);
      await writeSummary("## FPL forwarder deleted\n\nThe smoke path no longer answers as it.");
      return 0;
    }
    console.log(
      `::error::${SMOKE_URL} did not show the forwarder gone. Check the Worker and the ` +
        "Workers Routes of mymandev.com in the Cloudflare dashboard.",
    );
    return 1;
  }
  console.error(`unknown step ${JSON.stringify(step)}`);
  return 2;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv[2]).then(
    (code) => {
      process.exitCode = code;
    },
    (error) => {
      console.log(`::error::${error.message}`);
      process.exitCode = 1;
    },
  );
}
