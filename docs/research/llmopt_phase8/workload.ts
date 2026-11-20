/** The standard three-preference workload, through the real planner and transports. */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { createInterface } from "node:readline";
import {
  AdviceApiError,
  HttpAdviceClient,
} from "../../../web/src/features/league/advice/adviceClient";
import { deviceAdviceClient } from "../../../web/src/features/league/device/adviceClient";
import { replyTo } from "../../../web/src/features/league/device/replies";
import { withinCeiling } from "../../../web/src/features/league/device/solve/ceiling";
import { deviceWorkReceipt } from "../../../web/src/features/league/device/workBudget";
import { preparePlans } from "../../../web/src/features/league/llmopt/intent";
import { prepareConfirmedRun } from "../../../web/src/features/league/llmopt/releaseRun";
import {
  combinedCandidates,
  prepareCombined,
} from "../../../web/src/features/league/llmopt/combinedPlan";
import {
  preferenceExecution,
  preferenceStates,
} from "../../../web/src/features/league/llmopt/preferenceExecution";
import { followupRequests } from "../../../web/src/features/league/llmopt/planSlots";
import {
  expectedNet,
  transferPathKey,
} from "../../../web/src/features/league/llmopt/planComparison";
import { preferencePrice } from "../../../web/src/features/league/llmopt/planResults";

const lines = createInterface({ input: process.stdin })[Symbol.asyncIterator]();
async function read() {
  const row = await lines.next();
  if (row.done) throw new Error("Local API driver disconnected.");
  return JSON.parse(row.value);
}
async function driver(op, data = {}) {
  process.stdout.write(JSON.stringify({ op, ...data }) + "\n");
  return read();
}
const initial = await read();
const { block, document, squad, window, runId, enabled } = initial;
const require = createRequire(resolve("web/package.json"));
const storage = new Map();
Object.defineProperty(globalThis, "sessionStorage", {
  configurable: true,
  value: {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
  },
});
const held = new Set<number>(block.held);
const remote = new HttpAdviceClient("http://127.0.0.1", async (url, init) => {
  const target = new URL(url);
  if (target.hostname !== "127.0.0.1") throw new Error("Unexpected origin");
  const res = await driver("http", {
    path: target.pathname + target.search,
    method: init?.method ?? "GET",
    body: init?.body,
    headers: init?.headers,
  });
  return new Response(JSON.stringify(res.body), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
});
const deviceWork = [];
// Only replace the browser Worker message port. The production reply dispatcher,
// cumulative ceiling, WASM model, storage, cache and envelope processing run as usual.
function createSolver() {
  return {
    onmessage: undefined,
    onerror: undefined,
    terminate() {},
    async postMessage(request) {
      const start = performance.now();
      const calls = [];
      const wasm = await require("highs")({
        wasmBinary: readFileSync(require.resolve("highs/runtime")),
      });
      const loaded = performance.now();
      let outcome;
      replyTo(
        withinCeiling({
          solve(lp, options) {
            const at = performance.now();
            const answer = wasm.solve(lp, options);
            calls.push({
              status: answer.Status,
              seconds: (performance.now() - at) / 1000,
            });
            return answer;
          },
        }),
        request,
        (data) => {
          outcome = data.kind;
          this.onmessage({ data });
        },
      );
      deviceWork.push({
        bundle: !!request.preferenceBundle,
        outcome,
        calls,
        load_seconds: (loaded - start) / 1000,
        elapsed_seconds: (performance.now() - start) / 1000,
      });
    },
  };
}
const draft = {
  window,
  hard: [],
  soft: [
    { kind: "keep_player", player_id: block.held[0] },
    { kind: "keep_player", player_id: block.held[1] },
    { kind: "no_hits" },
  ],
};
const plans = preparePlans({ ...draft, soft: [] }, held);
function compact(state) {
  if (state.phase !== "done")
    return { status: state.phase, reason: state.reason ?? null };
  const p = state.envelope.payload;
  return {
    status: p.solver_status ?? state.phase,
    net: expectedNet(p),
    path: transferPathKey(p),
    source: state.source,
  };
}

async function replay(cache) {
  const workStart = deviceWork.length;
  const start = performance.now();
  await driver("begin", { cache });
  const client = deviceAdviceClient(
    remote,
    squad,
    async () => ({ payload: document }),
    createSolver,
  );
  const caps = await client.readCapabilities(squad.league_id);
  if ((caps?.llmoptVNext === true) !== enabled)
    throw new Error("Authoritative release capability mismatch.");
  const run = prepareConfirmedRun(
    { draft, held, plans },
    squad,
    false,
    caps,
    enabled ? runId : undefined,
  );
  if (!run?.baseRequest)
    throw new Error("Standard workload could not prepare its base request.");
  const execution = preferenceExecution(run);
  let stages = [];
  async function stage(label, requests) {
    const pending = [];
    for (const request of requests) {
      // Compute presses submit via the public transport, which serves a warm answer directly.
      let outcome;
      try {
        outcome = await client.requestAdvice(request);
      } catch (error) {
        if (!(error instanceof AdviceApiError)) throw error;
        outcome = {
          kind: "unavailable",
          reason: error.code ?? `HTTP_${error.status}`,
        };
      }
      pending.push({ request, outcome });
    }
    const jobs = pending
      .filter(({ outcome }) => outcome.kind === "job")
      .map(({ outcome }) => outcome.jobId);
    const drained = jobs.length ? await driver("drain", { jobs, label }) : [];
    const states = [];
    for (const { request, outcome } of pending) {
      let result = outcome;
      if (outcome.kind === "job") {
        const job = await client.readJob(outcome.jobId);
        result =
          job.status === "completed"
            ? await client.readAdvice(request)
            : { kind: "unavailable", reason: job.errorCode ?? job.status };
      }
      states.push(
        result.kind === "advice"
          ? {
              phase: "done",
              request,
              envelope: result.envelope,
              source: result.source,
            }
          : { phase: "failed", request, reason: result.reason ?? result.kind },
      );
    }
    stages.push({
      label,
      submissions: pending.map(({ outcome }) => outcome.kind),
      returned_job_ids: jobs,
      job_ids: drained,
    });
    return states;
  }
  const [base] = await stage("base", [run.baseRequest]);
  let states = {
    base,
    first: { phase: "idle" },
    second: { phase: "idle" },
    combined: { phase: "idle" },
  };
  if (base.phase === "done") {
    if (execution) {
      [states.first] = await stage("preference_bundle", [execution]);
      states = preferenceStates(states, run, execution);
    } else {
      const slots = followupRequests(run, base.envelope.payload).flatMap((s) =>
        s?.request ? [s.request] : [],
      );
      const prices = await stage("individual_prices", slots);
      [states.first, states.second] = prices;
      const reviews = run.prices.map((t) => ({
        outcome: t.outcome,
        price: preferencePrice(t, "", base, prices, false),
      }));
      const picked = combinedCandidates(run, reviews);
      const combined = picked && prepareCombined(run, picked);
      if (combined?.request)
        [states.combined] = await stage("combined", [combined.request]);
    }
  }
  const answers = Object.fromEntries(
    Object.entries(states).map(([key, state]) => [key, compact(state)]),
  );
  const paths = new Set(
    Object.values(answers)
      .map((r) => r.path)
      .filter(Boolean),
  );
  paths.delete(answers.base.path);
  return {
    cache,
    seconds: (performance.now() - start) / 1000,
    stages,
    answers,
    distinct_alternative_paths: paths.size,
    device_work: deviceWork.slice(workStart),
    device_units_cumulative: enabled
      ? (deviceWorkReceipt(runId)?.units ?? 0)
      : 0,
  };
}
const passes = [];
for (const cache of ["cold", "warm"]) passes.push(await replay(cache));
process.stdout.write(JSON.stringify({ op: "done", passes }) + "\n");
process.stdin.destroy();
