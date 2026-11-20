import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import fixture from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { publicEntryCapabilities } from "../advice/adviceCapabilities";
import type { AdviceClient } from "../advice/adviceClient";
import { PATIENCE_EXHAUSTED, QUEUE_PATIENCE_MS } from "../advice/useAdviceJob";
import { deviceAdviceClient } from "../device/adviceClient";
import type { LpSolver } from "../device/lp/problem";
import { replyTo } from "../device/replies";
import type { DevicePlanDocument, DevicePlanEntry } from "../device/types";
import type { DeviceSolver } from "../device/useDevicePlan";
import type { Constraint, PlanDraft } from "./intent";
import type { EntryAdvice } from "../types";
import {
  candidateRequest,
  computeRepairPlan,
  matchesRepair,
  verificationRequest,
} from "./repairComputation";

const require = createRequire(import.meta.url);
const document = fixture.document as unknown as DevicePlanDocument;
const entry = fixture.members[0]!.entry as unknown as DevicePlanEntry;
const example = mockEntrySquadEnvelopes[35249001]!.payload;
const squad = {
  ...example,
  season: document.season,
  gameweek: document.gameweek,
  source_snapshot_id: document.source_snapshot_id,
  device_plan: entry,
  bank_tenths: entry.bank_tenths,
  free_transfers: entry.free_transfers,
  starting_xi: example.starting_xi.map((p, i) => ({ ...p, player_id: entry.held[i]! })),
  bench: example.bench.map((p, i) => ({ ...p, player_id: entry.held[i + 11]! })),
};
const runId = "a".repeat(32);
let solver: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  solver = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60000);
beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto);
  sessionStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

function clientForFixture() {
  const remote = {
    readCapabilities: vi.fn().mockResolvedValue({
      ...publicEntryCapabilities(squad),
      llmoptVNext: true,
      verifiedRepairs: true,
    }),
    readAdvice: vi.fn(),
    requestAdvice: vi.fn(),
    readJob: vi.fn(),
    readPublished: vi.fn(),
  } satisfies AdviceClient;
  const posted = vi.fn();
  const client = deviceAdviceClient(
    remote,
    squad,
    async () => ({
      contract_version: "provisional_league_ui_v1",
      generated_at_utc: "2026-11-20T00:00:00Z",
      source_kind: "example",
      payload: document,
    }),
    () => {
      const worker: DeviceSolver = {
        onmessage: null,
        terminate: vi.fn(),
        postMessage(input) {
          posted(input);
          queueMicrotask(() =>
            replyTo(solver, input, (data) => worker.onmessage?.({ data } as MessageEvent)),
          );
        },
      };
      return worker;
    },
  );
  return { client, posted, remote };
}

it.each([false, true])(
  "recalculates the preference-selected one-week witness (priority program: %s)",
  async (priority) => {
    const { client, posted, remote } = clientForFixture();
    const dataId = await client.readDeviceDataId!();
    const owner = { runId, dataId, failedBase: true };
    const options = { squad, window: 1 as const };
    const soft: Constraint = {
      kind: "avoid_player",
      player_id: 158,
      ...(priority ? { priority: 1 as const } : {}),
    };
    const draft: PlanDraft = {
      hard: [],
      soft: [soft],
      ...(priority ? { max_total_cost_tenths: 1000 } : {}),
    };
    const request = candidateRequest(draft, options, owner, "repair")!;
    expect(request.preferenceBundle).toBeDefined();
    const compute = (query: typeof request) =>
      computeRepairPlan(
        client,
        query,
        document.source_snapshot_id,
        dataId,
        new AbortController().signal,
      );
    const witness = await compute(request);
    expect(
      [...(witness.starting_xi ?? []), ...(witness.bench ?? [])].map((p) => p.player_id),
    ).not.toContain(158);
    const parent = await client.requestAdvice(request);
    if (parent.kind !== "advice") throw new Error("Expected a completed preference run");
    // The hard-only parent keeps this player; using the parent as the witness would drop the preference.
    expect(
      [
        ...(parent.envelope.payload.starting_xi ?? []),
        ...(parent.envelope.payload.bench ?? []),
      ].map((p) => p.player_id),
    ).toContain(158);
    const verification = verificationRequest(request, witness)!;
    expect(verification.preferenceBundle).toEqual(request.preferenceBundle);
    const result = await compute(verification);
    expect(matchesRepair(witness, result)).toBe(true);
    expect(matchesRepair(parent.envelope.payload, result)).toBe(false);
    expect(posted).toHaveBeenCalledTimes(2);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  },
);

it("requires room for all three-week preference stages and allows a redundant priced preference", () => {
  const owner = { runId, dataId: "b".repeat(64), failedBase: true };
  const options = { squad, window: 3 as const };
  const keep: Constraint = { kind: "keep_player", player_id: entry.held[0]! };
  expect(() => candidateRequest({ hard: [], soft: [keep] }, options, owner, "repair")).toThrow(
    "RUN_BUDGET_EXHAUSTED",
  );
  const alreadyRequired = candidateRequest(
    { hard: [keep], soft: [keep] },
    options,
    owner,
    "repair",
  );
  expect(alreadyRequired?.preferences.keep_players).toEqual([entry.held[0]]);
  expect(alreadyRequired?.run?.stage).toBe("repair");
});

it("accepts a complete feasible witness and refuses incomplete or unproved cached answers", async () => {
  const { client } = clientForFixture();
  const dataId = await client.readDeviceDataId!();
  const request = candidateRequest(
    { hard: [{ kind: "keep_player", player_id: entry.held[0]! }], soft: [] },
    { squad, window: 1 },
    { runId, dataId, failedBase: true },
    "repair",
  )!;
  const outcome = await client.requestAdvice(request);
  if (outcome.kind !== "advice") throw new Error("A completed native fixture witness was required");
  function altered(change: (plan: EntryAdvice) => void) {
    const response = structuredClone(outcome);
    if (response.kind !== "advice") throw new Error("Invalid fixture response");
    change(response.envelope.payload);
    return computeRepairPlan(
      { ...client, requestAdvice: async () => response },
      request,
      document.source_snapshot_id,
      dataId,
      new AbortController().signal,
    );
  }
  await expect(
    altered((p) => {
      p.solver_status = "FEASIBLE";
    }),
  ).resolves.toMatchObject({ solver_status: "FEASIBLE" });
  await expect(
    altered((p) => {
      delete p.device_input_fingerprint;
      p.plan_data_id = dataId;
    }),
  ).rejects.toThrow("RUN_CONTEXT_CHANGED");
  await expect(
    altered((p) => {
      p.wall_clock_stopped_the_search = true;
    }),
  ).rejects.toThrow("RUN_BUDGET_EXHAUSTED");
  for (const mutation of [
    (p: EntryAdvice) => {
      p.data_quality = "empty";
    },
    (p: EntryAdvice) => {
      p.solver_status = "UNKNOWN";
    },
    (p: EntryAdvice) => {
      delete p.solver_status;
    },
    (p: EntryAdvice) => {
      p.plan_weeks = [];
    },
    (p: EntryAdvice) => {
      p.plan_weeks![0]!.gameweek++;
    },
    (p: EntryAdvice) => {
      delete p.plan_weeks![0]!.lineup;
    },
    (p: EntryAdvice) => {
      const lineup = p.plan_weeks![0]!.lineup!;
      lineup.bench[0] = lineup.starting_xi[0]!;
    },
    (p: EntryAdvice) => {
      const lineup = p.plan_weeks![0]!.lineup!;
      lineup.vice_captain = lineup.captain;
    },
    (p: EntryAdvice) => {
      p.starting_xi = [];
    },
  ])
    await expect(altered(mutation)).rejects.toThrow();
});

it.each(["failed", "cancelled"] as const)(
  "rejects a %s repair job without reading a previous cached match",
  async (status) => {
    const request = candidateRequest(
      { hard: [], soft: [] },
      { squad, window: 3 },
      { runId, dataId: "b".repeat(64), failedBase: true },
      "repair",
    )!;
    const client = {
      requestAdvice: vi.fn().mockResolvedValue({ kind: "job", jobId: "old" }),
      readJob: vi.fn().mockResolvedValue({ jobId: "old", status, errorCode: "RUN_CANCELLED" }),
      readCapabilities: vi.fn().mockResolvedValue({
        ...publicEntryCapabilities(squad),
        llmoptVNext: true,
        verifiedRepairs: true,
      }),
      readAdvice: vi.fn(),
      readPublished: vi.fn(),
    } satisfies AdviceClient;
    await expect(
      computeRepairPlan(
        client,
        request,
        document.source_snapshot_id,
        "b".repeat(64),
        new AbortController().signal,
      ),
    ).rejects.toThrow("RUN_CANCELLED");
    expect(client.readAdvice).not.toHaveBeenCalled();
  },
);

it("stops polling a queued repair at the normal queue deadline and on cancellation", async () => {
  vi.useFakeTimers();
  try {
    const owner = { runId, dataId: "c".repeat(64), failedBase: true };
    const query = candidateRequest({ hard: [], soft: [] }, { squad, window: 3 }, owner, "repair")!;
    const client = {
      requestAdvice: vi.fn().mockResolvedValue({ kind: "job", jobId: "job", status: "queued" }),
      readJob: vi.fn().mockResolvedValue({ jobId: "job", status: "queued" }),
      readCapabilities: vi.fn().mockResolvedValue({
        ...publicEntryCapabilities(squad),
        llmoptVNext: true,
        verifiedRepairs: true,
      }),
      readAdvice: vi.fn(),
      readPublished: vi.fn(),
    } satisfies AdviceClient;
    const first = new AbortController();
    const attempt = (signal: AbortSignal) =>
      computeRepairPlan(client, query, document.source_snapshot_id, owner.dataId, signal);
    const expired = expect(attempt(first.signal)).rejects.toThrow(PATIENCE_EXHAUSTED);
    await vi.advanceTimersByTimeAsync(QUEUE_PATIENCE_MS);
    await expired;
    const second = new AbortController();
    const cancelled = expect(attempt(second.signal)).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(1);
    const polls = client.readJob.mock.calls.length;
    second.abort();
    await cancelled;
    expect(client.readJob.mock.calls).toHaveLength(polls);
    expect(client.requestAdvice).toHaveBeenCalledTimes(2);
    expect(client.readAdvice).not.toHaveBeenCalled();
  } finally {
    vi.useRealTimers();
  }
});
