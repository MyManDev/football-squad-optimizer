// The step of .github/workflows/deploy-deadline-push.yml that reads better, and can be tested,
// as JavaScript rather than shell: smoke the deployed Worker by reading its public key. Run as
// `node workers/deadline-push/scripts/deploy-steps.mjs smoke` from the repository root. It
// reads no credential: wrangler holds those.

import { appendFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

import { KEY_CONTRACT, MARKER_HEADER, MARKER_VALUE, SITE_ORIGIN } from "../src/rules.js";

/** The one public, read-only path: it names the VAPID public key and nothing of anyone. */
export const SMOKE_URL = `${SITE_ORIGIN}/api/v1/push/key`;

async function readAnswer(fetchImpl, url, timeoutMs) {
  try {
    const response = await fetchImpl(url, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
    });
    const text = await response.text();
    let body = null;
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
    return { status: response.status, body, marked: response.headers.get(MARKER_HEADER) === MARKER_VALUE };
  } catch (error) {
    return { status: null, body: null, marked: false, error: `${error.name}: ${error.message}` };
  }
}

/** A deployed Worker answers the key route with a marked key document carrying a P-256 point. */
export function isKeyAnswer(answer) {
  return (
    answer.status === 200 &&
    answer.marked &&
    answer.body !== null &&
    answer.body.contract_version === KEY_CONTRACT &&
    typeof answer.body.public_key === "string" &&
    /^[A-Za-z0-9_-]{87}$/.test(answer.body.public_key)
  );
}

/**
 * Up to `attempts` reads a few seconds apart: the route can take a moment after a deploy. The
 * result says whether the Worker answers and what the last read gave.
 */
export async function smoke({ fetchImpl = globalThis.fetch, attempts = 6, sleep, log = console.log } = {}) {
  const wait = sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  let last = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    last = await readAnswer(fetchImpl, SMOKE_URL, 10_000);
    if (isKeyAnswer(last)) {
      log(`smoke: the reminder Worker answers its key (attempt ${attempt})`);
      return { ok: true, attempts: attempt, last };
    }
    log(`smoke: attempt ${attempt} gave status ${last.status} marked=${last.marked}${last.error ? ` ${last.error}` : ""}`);
    if (attempt < attempts) await wait(5_000);
  }
  return { ok: false, attempts, last };
}

async function summarize(lines) {
  const path = process.env.GITHUB_STEP_SUMMARY;
  if (!path) return;
  await appendFile(path, `${lines.join("\n")}\n`);
}

async function main(step) {
  if (step !== "smoke") {
    console.error("usage: node workers/deadline-push/scripts/deploy-steps.mjs smoke");
    return 2;
  }
  const result = await smoke();
  await summarize([
    "## Deadline reminder Worker: smoke",
    `- Key route answers: ${result.ok ? "yes" : "no"} after ${result.attempts} attempt(s)`,
    `- Last status: ${result.last?.status ?? "none"}`,
  ]);
  return result.ok ? 0 : 1;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  process.exitCode = await main(process.argv[2]);
}
