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
import { shownPriorityReference } from "../device/priorityWitness";
import { replyTo } from "../device/replies";
import { withinCeiling } from "../device/solve/ceiling";
import { solvePlan } from "../device/solve/week";
import type { DevicePlanDocument, DevicePlanEntry } from "../device/types";
import type { DeviceSolver } from "../device/useDevicePlan";
import { deviceWorkReceipt } from "../device/workBudget";
import type { Constraint, PlanDraft } from "./intent";
import type { EntryAdvice } from "../types";
import { expectedNet } from "./planComparison";
import { ruleRepairChoices } from "./ruleRepairChoices";
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

function clientForFixture(inputs = document, native: LpSolver = solver) {
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
  const posted = vi.fn<DeviceSolver["postMessage"]>();
  const client = deviceAdviceClient(
    remote,
    squad,
    async () => ({
      contract_version: "provisional_league_ui_v1",
      generated_at_utc: "2026-11-20T00:00:00Z",
      source_kind: "example",
      payload: inputs,
    }),
    () => {
      const worker: DeviceSolver = {
        onmessage: null,
        terminate: vi.fn(),
        postMessage(input) {
          posted(input);
          queueMicrotask(() =>
            replyTo(withinCeiling(native), input, (data) =>
              worker.onmessage?.({ data } as MessageEvent),
            ),
          );
        },
      };
      return worker;
    },
  );
  return { client, posted, remote };
}

it("solves just the mandatory transfer witness and its independent confirmation", async () => {
  const target = 104;
  const available = new Set([...entry.held, target]);
  const tiny = { ...document, players: document.players.filter((p) => available.has(p.id)) };
  const { client, posted, remote } = clientForFixture(tiny);
  const dataId = await client.readDeviceDataId!();
  const request = candidateRequest(
    { hard: [{ kind: "buy_player", player_id: target, week: 1 }], soft: [] },
    { squad, window: 1 },
    { runId, dataId, failedBase: false },
    "base",
  )!;
  expect(request.preferences.net_points_priority).toBe(true);
  const core = solvePlan(solver, tiny, entry, undefined, null, {
    preferences: request.preferences,
  });
  const compute = (query: typeof request) =>
    computeRepairPlan(client, query, tiny.source_snapshot_id, dataId, new AbortController().signal);
  const witness = await compute(request);
  const confirmation = await compute(verificationRequest(request, witness)!);
  expect(core.transfers_in).toEqual([target]);
  for (const answer of [witness, confirmation]) {
    const week = answer.plan_weeks![0]!;
    expect(week.transfers_in.map((p) => p.player_id)).toEqual(core.transfers_in);
    expect(week.transfers_out.map((p) => p.player_id)).toEqual(core.transfers_out);
    expect(new Set(week.lineup!.starting_xi.map((p) => p.player_id))).toEqual(
      new Set(core.starting_xi),
    );
    expect(week.lineup!.captain.player_id).toBe(core.captain);
    expect(expectedNet(answer)).toBeCloseTo(
      core.expected_own_points - core.transfer_hit_points,
      10,
    );
    expect(answer.device_alternatives).toBeUndefined();
  }
  expect(matchesRepair(witness, confirmation)).toBe(true);
  expect(posted).toHaveBeenCalledTimes(2);
  for (const [input] of posted.mock.calls) {
    expect(input.preferences).toEqual(request.preferences);
    expect(input).not.toHaveProperty("alternatives");
  }
  expect(remote.requestAdvice).not.toHaveBeenCalled();
});

it.each(["individual", "proved main", "unproved main"])(
  "recalculates and restores the preferred one-week repair with %s",
  async (mode) => {
    const priority = mode !== "individual";
    let interruptMain = mode === "unproved main";
    const { client, posted, remote } = clientForFixture(document, {
      solve(problem, options) {
        const answer = solver.solve(problem, options);
        if (!interruptMain) return answer;
        // Keep the real integer incumbent, but simulate the main search ending without a proof.
        interruptMain = false;
        return { ...answer, Status: "Time limit reached", ObjectiveValue: 1e9 };
      },
    });
    const dataId = await client.readDeviceDataId!();
    const owner = { runId, dataId, failedBase: true };
    const options = { squad, window: 1 as const };
    const soft: Constraint = {
      kind: "avoid_player",
      player_id: 158,
      ...(priority ? { priority: 1 as const } : {}),
    };
    const draft: PlanDraft = {
      hard: priority ? [{ kind: "buy_player", week: 1, player_id: 104 }] : [],
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
    for (const [input] of posted.mock.calls) expect(input).not.toHaveProperty("alternatives");
    if (priority) {
      const main = parent.envelope.payload;
      const [candidate, replay] = posted.mock.calls.map(([input]) => input);
      expect(main.solver_status).toBe(mode === "proved main" ? "OPTIMAL" : "FEASIBLE");
      expect(candidate!.priorityMain).toBe(true);
      expect(candidate!.priorityReference).toBeUndefined();
      expect(replay!.priorityMain).toBeUndefined();
      expect(replay!.priorityReference).toEqual(shownPriorityReference(main));
      for (const plan of [main, witness, result]) {
        expect(plan.plan_weeks![0]!.transfers_in.map((p) => p.player_id)).toContain(104);
      }
      for (const plan of [witness, result]) {
        expect(plan.priority_preferences!.reference_proved).toBe(main.solver_status === "OPTIMAL");
        expect(plan.priority_preferences!.total_cost).toBeCloseTo(
          expectedNet(main)! - expectedNet(plan)!,
          10,
        );
      }
      const beforeReload = deviceWorkReceipt(runId);
      expect(beforeReload?.units).toBe(8);
      const restored = clientForFixture();
      const repeated = await computeRepairPlan(
        restored.client,
        verification,
        document.source_snapshot_id,
        dataId,
        new AbortController().signal,
      );
      expect(matchesRepair(witness, repeated)).toBe(true);
      expect(deviceWorkReceipt(runId)).toEqual(beforeReload);
      expect(restored.posted).not.toHaveBeenCalled();
      expect(restored.remote.requestAdvice).not.toHaveBeenCalled();
    }
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

it("binds both preflight club candidates to the same original using the page's choices", () => {
  const sourceDraft: PlanDraft = {
    window: 3,
    soft: [],
    hard: [
      { kind: "hold_transfers" },
      { kind: "club_count", club: "Club 1", count: 3 },
      { kind: "club_count", club: "Club 1", count: 2 },
    ],
  };
  const choices = ruleRepairChoices(sourceDraft, {
    gameweek: squad.gameweek,
    window: 3,
    held: new Set(entry.held),
    language: "en",
    players: [],
    frozen: [],
  })!.choices;
  expect(choices).toHaveLength(2);
  const owner = { runId, dataId: "b".repeat(64), failedBase: false, sourceDraft };
  const basis = { squad, window: 3 as const };
  const [first, second] = choices.map(({ draft }, i) =>
    candidateRequest(draft, basis, owner, i === 0 ? "base" : "repair")!,
  );
  expect(first!.preferences.club_counts?.[0]?.count).toBe(2);
  expect(second!.preferences.club_counts?.[0]?.count).toBe(3);
  const original = first!.run!.repair_origin!;
  expect(original).toEqual(second!.run!.repair_origin);
  expect(original.preferences.flatMap((p) => p.club_counts ?? []).map((r) => r.count)).toEqual([
    3, 2,
  ]);
  expect(original.preferences.some((p) => p.hold_transfers)).toBe(true);
  expect(original.preferences.some((p) => p.save_chips)).toBe(true);
  expect(
    candidateRequest(choices[0]!.draft, basis, { ...owner, failedBase: true }, "repair")!.run,
  ).not.toHaveProperty("repair_origin");
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
