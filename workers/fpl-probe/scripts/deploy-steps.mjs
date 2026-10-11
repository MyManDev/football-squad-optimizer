// The steps of .github/workflows/deploy-fpl-probe.yml that read better, and can be tested, as
// JavaScript rather than shell: find the probe's KV namespace in wrangler's listing, write its
// id into wrangler.toml on the runner, choose when the deployed probe stops, smoke it, and
// confirm a deleted one is gone. Run as `node workers/fpl-probe/scripts/deploy-steps.mjs <step>`
// from the repository root. It reads no credential: wrangler-action holds those.

import { appendFile, readFile, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

import { MARKER_VALUE, NOW_HEADER_VALUE, PROBE_DAYS, PROBE_HEADER } from "../src/probe.js";

export const NAMESPACE_TITLE = "squadopt-fpl-probe";
export const PLACEHOLDER = "FILLED_IN_BY_THE_DEPLOY_WORKFLOW";
export const CONFIG_PATH = "workers/fpl-probe/wrangler.toml";
export const RESULTS_URL = "https://squadopt.mymandev.com/api/v1/fpl-probe";
export const NOW_URL = `${RESULTS_URL}/now`;

const NAMESPACE_ID = /^[0-9a-f]{32}$/;

/** The JSON array in wrangler's `kv namespace list` output, skipping any banner before it. */
export function namespacesFrom(listing) {
  const lines = String(listing ?? "").split(/\r?\n/);
  const start = lines.findIndex((line) => line.trimStart().startsWith("["));
  if (start === -1) throw new Error("wrangler's namespace listing holds no JSON array");
  const text = lines.slice(start).join("\n");
  for (let end = text.lastIndexOf("]"); end !== -1; end = text.lastIndexOf("]", end - 1)) {
    try {
      const parsed = JSON.parse(text.slice(0, end + 1));
      if (Array.isArray(parsed)) return parsed;
    } catch {
      // A shorter prefix may still be the array; keep looking.
    }
  }
  throw new Error("wrangler's namespace listing holds no JSON array");
}

/** The id of the namespace titled `title`, null when there is none, an error when ambiguous. */
export function namespaceId(listing, title = NAMESPACE_TITLE) {
  const matches = namespacesFrom(listing).filter((entry) => entry?.title === title);
  if (matches.length > 1) {
    throw new Error(`${matches.length} KV namespaces are titled ${title}; remove the extras first`);
  }
  if (matches.length === 0) return null;
  const { id } = matches[0];
  if (typeof id !== "string" || !NAMESPACE_ID.test(id)) {
    throw new Error(`the KV namespace titled ${title} has an id of an unexpected shape`);
  }
  return id;
}

/** wrangler.toml with the placeholder replaced; refuses unless the placeholder is there once. */
export function withNamespaceId(config, id) {
  if (typeof id !== "string" || !NAMESPACE_ID.test(id)) {
    throw new Error("no KV namespace id of the expected shape was found or created");
  }
  const line = `id = "${PLACEHOLDER}"`;
  const count = config.split(line).length - 1;
  if (count !== 1) {
    throw new Error(`${CONFIG_PATH} must hold the placeholder id line once; it holds ${count}`);
  }
  return config.replace(line, `id = "${id}"`);
}

/**
 * The PROBE_UNTIL the deploy passes to the Worker: PROBE_DAYS after `fromMs`, as an ISO time.
 * wrangler's --var keeps everything after the first colon, so the time's own colons survive.
 */
export function probeUntil(fromMs, days = PROBE_DAYS) {
  if (!Number.isFinite(fromMs)) throw new Error("the deploy time is not a time");
  return new Date(fromMs + days * 86_400_000).toISOString();
}

async function readAnswer(fetchImpl, url, timeoutMs, headers = {}) {
  try {
    const response = await fetchImpl(url, {
      headers: { accept: "application/json", ...headers },
      signal: AbortSignal.timeout(timeoutMs),
    });
    const text = await response.text();
    const contentType = response.headers.get("content-type") ?? "";
    const marked = response.headers.get(PROBE_HEADER) === MARKER_VALUE;
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

function isProbeRecord(record) {
  return record !== null && typeof record === "object" && typeof record.target === "string";
}

/**
 * Whether an answer from /now came from the probe Worker. A 200 carrying records counts
 * whatever those records say: FPL refusing is the measurement, not a failed deploy. A 429 is
 * the Worker's own gate (once a minute, 48 times a UTC day). A 410 is the Worker saying it has
 * ended, which right after a deploy means PROBE_UNTIL did not arrive. Anything else, including
 * the site's HTML shell when the route has not taken the path yet, is not the Worker.
 */
export function judgeNow(answer) {
  const { status, body } = answer;
  const records = Array.isArray(body?.records) ? body.records : [];
  if (status === 200 && records.length > 0 && records.every(isProbeRecord)) return "records";
  if (status === 429 && body?.error === "too_many_requests") return "gated";
  if (status === 410 && body?.error === "ended") return "ended";
  return null;
}

/** Whether an answer from the results path is the probe Worker's. */
export function isProbeResults(answer) {
  return answer.status === 200 && Array.isArray(answer.body?.records) && !!answer.body?.summary;
}

/**
 * Whether an answer shows the probe Worker gone: an HTTP answer without the Worker's marker
 * header, such as the site's own page. No answer at all, any answer the Worker marked (its 404,
 * 429, 500 or 503 included), and Cloudflare's own 429 or 5xx in front of it prove nothing.
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

/**
 * Ask /now until the Worker answers, a few times while a new route reaches the edge. Returns
 * { ok, now, results } where `results` is read only when /now was gated.
 */
export async function smoke({
  fetchImpl = fetch,
  attempts = 6,
  waitMs = 10_000,
  timeoutMs = 40_000,
  sleep = pause,
  log = console.log,
} = {}) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const now = await readAnswer(fetchImpl, NOW_URL, timeoutMs, {
      [PROBE_HEADER]: NOW_HEADER_VALUE,
    });
    const verdict = judgeNow(now);
    if (verdict === "records") return { ok: true, now, results: null };
    if (verdict === "ended") {
      log("the Worker answers that the probe has ended: the deploy passed no PROBE_UNTIL ahead");
      return { ok: false, now, results: null };
    }
    if (verdict === "gated") {
      const results = await readAnswer(fetchImpl, RESULTS_URL, timeoutMs);
      return { ok: isProbeResults(results), now, results };
    }
    log(`attempt ${attempt} of ${attempts}: ${described(now)}, not the probe's answer yet`);
    if (attempt < attempts) await sleep(waitMs);
  }
  return { ok: false, now: null, results: null };
}

/**
 * After a Worker delete: the results path must stop answering as the Worker within a minute or
 * so. Only an answer that shows it gone counts; anything else is asked again.
 */
export async function confirmGone({
  fetchImpl = fetch,
  attempts = 6,
  waitMs = 10_000,
  timeoutMs = 20_000,
  sleep = pause,
  log = console.log,
} = {}) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const answer = await readAnswer(fetchImpl, RESULTS_URL, timeoutMs);
    if (showsGone(answer)) return true;
    const seen = answer.marked
      ? `the Worker still answers (HTTP ${answer.status})`
      : described(answer);
    log(`attempt ${attempt} of ${attempts}: ${seen}`);
    if (attempt < attempts) await sleep(waitMs);
  }
  return false;
}

async function writeOutput(name, value) {
  if (process.env.GITHUB_OUTPUT) await appendFile(process.env.GITHUB_OUTPUT, `${name}=${value}\n`);
}

async function writeSummary(markdown) {
  if (process.env.GITHUB_STEP_SUMMARY) {
    await appendFile(process.env.GITHUB_STEP_SUMMARY, `${markdown}\n`);
  }
}

function fenced(value) {
  return ["```json", JSON.stringify(value, null, 2), "```"].join("\n");
}

async function main(step) {
  if (step === "find-namespace") {
    const id = namespaceId(process.env.LISTING);
    console.log(id === null ? `no KV namespace is titled ${NAMESPACE_TITLE}` : `found ${id}`);
    await writeOutput("id", id ?? "");
    return 0;
  }
  if (step === "fill-namespace-id") {
    const config = await readFile(CONFIG_PATH, "utf8");
    await writeFile(CONFIG_PATH, withNamespaceId(config, process.env.NAMESPACE_ID ?? ""));
    console.log(`${CONFIG_PATH} now names the namespace on this runner only`);
    return 0;
  }
  if (step === "end-date") {
    const until = probeUntil(Date.now());
    console.log(`the probe asks FPL nothing from ${until}`);
    await writeOutput("until", until);
    return 0;
  }
  if (step === "smoke") {
    const { ok, now, results } = await smoke();
    if (!ok) {
      console.log(`::error::The probe Worker did not answer ${NOW_URL} with its JSON.`);
      return 1;
    }
    const shown = results === null ? now.body.records : results.body.summary;
    const heading =
      results === null
        ? "Live probe records (a refusal by FPL is the measurement, not a failure)"
        : "The live probe ran within the last minute; the stored summary instead";
    console.log(JSON.stringify(shown, null, 2));
    await writeSummary(`## ${heading}\n\n${fenced(shown)}`);
    return 0;
  }
  if (step === "confirm-gone") {
    if (await confirmGone()) {
      console.log(`${RESULTS_URL} no longer answers as the probe`);
      await writeSummary(
        "## FPL probe Worker deleted\n\nThe results path no longer answers as the probe.",
      );
      return 0;
    }
    console.log(
      `::error::${RESULTS_URL} did not show the probe gone, so its KV namespace is kept. ` +
        "Check the Worker and the Workers Routes of mymandev.com in the Cloudflare dashboard.",
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
