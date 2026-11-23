import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { webcrypto } from "node:crypto";
import { beforeAll, beforeEach, afterEach, describe, it, expect, vi } from "vitest";
import fixture from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { checkedPreferences } from "../advice/decisionPreferences";
import { publicEntryCapabilities } from "../advice/adviceCapabilities";
import type { PreferenceBundle } from "../advice/preferenceBundle";
import type { AdviceClient, AdviceRequest } from "../advice/adviceClient";
import { deviceAdviceClient } from "./adviceClient";
import { DEVICE_ENVELOPE_PREFIX } from "./envelopeCache";
import { deviceWorkReceipt } from "./workBudget";
import { shownPriorityReference } from "./priorityWitness";
import { planIdentity } from "../llmopt/planHistory";
import { expectedNet } from "../llmopt/planComparison";
import { replyTo } from "./replies";
import { solvePlan } from "./solve/week";
import type { DeviceSolver } from "./useDevicePlan";
import type { LpSolver } from "./lp/problem";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";

const require = createRequire(import.meta.url);
let solver: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  solver = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);
beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto);
  sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const document = fixture.document as unknown as DevicePlanDocument;
const entry = fixture.members[0]!.entry as unknown as DevicePlanEntry;
const squad = {
  ...mockEntrySquadEnvelopes[35249001]!.payload,
  source_snapshot_id: document.source_snapshot_id,
  season: document.season,
  gameweek: document.gameweek,
  device_plan: entry,
  bank_tenths: entry.bank_tenths,
  free_transfers: entry.free_transfers,
  starting_xi: entry.held.slice(0, 11).map((id, i) => ({
    ...mockEntrySquadEnvelopes[35249001]!.payload.starting_xi[i]!,
    player_id: id,
  })),
  bench: entry.held.slice(11).map((id, i) => ({
    ...mockEntrySquadEnvelopes[35249001]!.payload.bench[i]!,
    player_id: id,
  })),
};
const request: AdviceRequest = {
  leagueId: 352490,
  entryId: squad.entry.entry_id,
  season: document.season,
  gameweek: document.gameweek,
  strategy: "saf-puan",
  window: 1,
  run: { contract_version: "llmopt_run_v1", run_id: "d".repeat(32), stage: "base" },
  preferences: checkedPreferences({ keep_players: [entry.held[0]], net_points_priority: true }),
};
const enabledCaps = {
  ...publicEntryCapabilities(squad),
  llmoptVNext: true as const,
  verifiedRepairs: true as const,
};
function setup(deviceSolver: LpSolver = solver) {
  const remote = {
    readAdvice: vi.fn().mockResolvedValue({ kind: "not-computed" }),
    readPublished: vi.fn().mockResolvedValue({ kind: "not-computed" }),
    requestAdvice: vi.fn().mockResolvedValue({ kind: "unavailable" }),
    readJob: vi.fn(),
    cancelRun: vi.fn(),
    readCapabilities: vi.fn().mockResolvedValue(enabledCaps),
    readPublicCapabilities: vi.fn().mockResolvedValue({ ...enabledCaps, leagueId: 0 }),
  } satisfies AdviceClient;
  const posts = vi.fn();
  const create = () => {
    const worker: DeviceSolver = {
      onmessage: null,
      terminate: vi.fn(),
      postMessage: (input) => {
        posts(input);
        queueMicrotask(() =>
          replyTo(deviceSolver, input, (data) => worker.onmessage?.({ data } as MessageEvent)),
        );
      },
    };
    return worker;
  };
  const load = async () => ({
    contract_version: "provisional_league_ui_v1" as const,
    generated_at_utc: "2026-11-19T00:00:00Z",
    source_kind: "example" as const,
    payload: document,
  });
  return { remote, posts, create, load, client: deviceAdviceClient(remote, squad, load, create) };
}

describe("one-week advice transport with a real solver", () => {
  it.each(["candidate", "selection"] as const)(
    "recovers an aborted %s without a concurrent duplicate or a refund",
    async (stage) => {
      const { client, remote, load, posts, create } = setup();
      const dataId = await client.readDeviceDataId!();
      const candidate: AdviceRequest = {
        ...request,
        run: { ...request.run!, stage: "repair" },
        deviceRepair: { dataId },
      };
      const verify = stage === "selection";
      if (verify) expect((await client.requestAdvice(candidate)).kind).toBe("advice");
      const attempt = { ...candidate, deviceRepair: { dataId, verify } };
      const runId = request.run!.run_id;
      let started!: () => void;
      const posted = new Promise<void>((resolve) => {
        started = resolve;
      });
      const terminated = vi.fn();
      const waiting = deviceAdviceClient(remote, squad, load, () => ({
        onmessage: null,
        terminate: terminated,
        postMessage: started,
      }));
      const controller = new AbortController();
      const first = waiting.requestAdvice(attempt, { signal: controller.signal });
      await posted;
      const reserved = deviceWorkReceipt(runId)!;
      expect(reserved.units).toBe(verify ? 8 : 4);
      // The concurrent client reaches the same address while the first worker is still alive.
      let observed!: () => void;
      const lookup = new Promise<void>((resolve) => {
        observed = resolve;
      });
      const original = Storage.prototype.getItem;
      const reads = vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (
        this: Storage,
        key,
      ) {
        if (key.startsWith(DEVICE_ENVELOPE_PREFIX)) observed();
        return original.call(this, key);
      });
      const other = deviceAdviceClient(remote, squad, load, create);
      const joined = Promise.allSettled([first, other.requestAdvice(attempt)]);
      await lookup;
      reads.mockRestore();
      controller.abort();
      const interrupted = {
        status: "rejected",
        reason: expect.objectContaining({ name: "AbortError" }),
      };
      expect(await joined).toMatchObject([interrupted, interrupted]);
      expect(terminated).toHaveBeenCalledOnce();
      expect(deviceWorkReceipt(runId)).toEqual(reserved);
      expect(Object.keys(sessionStorage).some((key) => key.endsWith(":failure"))).toBe(false);
      expect(posts).toHaveBeenCalledTimes(verify ? 1 : 0);
      const resumed = deviceAdviceClient(remote, squad, load, create);
      remote.readCapabilities.mockResolvedValue({ ...enabledCaps, verifiedRepairs: undefined });
      expect(await resumed.requestAdvice(attempt)).toMatchObject({
        reason: "LLMOPT_VNEXT_DISABLED",
      });
      expect(deviceWorkReceipt(runId)).toEqual(reserved);
      remote.readCapabilities.mockResolvedValue(enabledCaps);
      const recovered = await resumed.requestAdvice(attempt);
      expect(recovered.kind).toBe("advice");
      expect(await resumed.requestAdvice(attempt)).toEqual(recovered);
      expect(deviceWorkReceipt(runId)).toEqual({ ...reserved, units: reserved.units + 4 });
      expect(posts).toHaveBeenCalledTimes(verify ? 2 : 1);
      expect(remote.requestAdvice).not.toHaveBeenCalled();
    },
  );

  it("restores the exact storage left by a page that disappeared during selected replay", async () => {
    const { client, remote, load, create, posts } = setup();
    const dataId = await client.readDeviceDataId!();
    const candidate: AdviceRequest = {
      ...request,
      run: { ...request.run!, stage: "repair" },
      deviceRepair: { dataId },
    };
    const witness = await client.requestAdvice(candidate);
    if (witness.kind !== "advice") throw new Error("Missing candidate witness");
    const select = { ...candidate, deviceRepair: { dataId, verify: true } };
    let snapshot: [string, string][] = [];
    const original = deviceAdviceClient(remote, squad, load, () => {
      snapshot = Object.keys(sessionStorage).map((key) => [key, sessionStorage.getItem(key)!]);
      return create();
    });
    expect((await original.requestAdvice(select)).kind).toBe("advice");
    sessionStorage.clear();
    for (const [key, value] of snapshot) sessionStorage.setItem(key, value);
    const runId = request.run!.run_id;
    const abandoned = deviceWorkReceipt(runId)!;
    expect(abandoned.units).toBe(8);
    expect(abandoned.repairSelection).toBe(abandoned.repairCandidates![0]);
    expect(Object.keys(sessionStorage).some((key) => key.endsWith(":selection"))).toBe(false);
    const restored = deviceAdviceClient(remote, squad, load, create);
    const replay = await restored.requestAdvice(select);
    if (replay.kind !== "advice") throw new Error("Missing recovered selection");
    expect(await planIdentity(replay.envelope.payload)).toBe(
      await planIdentity(witness.envelope.payload),
    );
    expect(expectedNet(replay.envelope.payload)).toBe(expectedNet(witness.envelope.payload));
    expect(await restored.requestAdvice(select)).toEqual(replay);
    expect(deviceWorkReceipt(runId)).toEqual({ ...abandoned, units: 12 });
    expect(posts).toHaveBeenCalledTimes(3);
  });

  it("computes a repair and freshly verifies the selected content once across reload", async () => {
    const { client, remote, posts, load, create } = setup();
    const dataId = await client.readDeviceDataId!();
    const failed = await client.requestAdvice({
      ...request,
      preferences: checkedPreferences({
        net_points_priority: true,
        min_bank: { tenths: 10000 },
      }),
    });
    expect(failed).toEqual({
      kind: "unavailable",
      reason: "PLAN_NOT_FOUND",
      infeasibility: { repairs: [] },
    });
    const candidate: AdviceRequest = {
      ...request,
      run: { ...request.run!, stage: "repair" },
      deviceAlternatives: true,
      deviceRepair: { dataId },
    };
    const witness = await client.requestAdvice(candidate);
    if (witness.kind !== "advice") throw new Error("A feasible witness was required.");
    expect(posts).toHaveBeenCalledTimes(2);
    const selected = { ...candidate, deviceRepair: { dataId, verify: true } };
    const [a, b] = await Promise.all([
      client.requestAdvice(selected),
      client.requestAdvice(selected),
    ]);
    expect(a).toEqual(b);
    if (a.kind !== "advice") throw new Error("The selected repair was not verified.");
    expect(await planIdentity(a.envelope.payload)).toBe(
      await planIdentity(witness.envelope.payload),
    );
    expect(expectedNet(a.envelope.payload)).toBe(expectedNet(witness.envelope.payload));
    expect(posts).toHaveBeenCalledTimes(3);
    remote.readCapabilities.mockResolvedValue(publicEntryCapabilities(squad));
    const restored = deviceAdviceClient(remote, squad, load, create);
    expect(await restored.requestAdvice(selected)).toEqual(a);
    expect(await restored.requestAdvice(candidate)).toEqual(witness);
    expect(posts).toHaveBeenCalledTimes(3);
    expect(deviceWorkReceipt(request.run!.run_id)?.units).toBe(12);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });
  it.each([
    ["no master", { ...enabledCaps, llmoptVNext: undefined }],
    ["no repair support", { ...enabledCaps, verifiedRepairs: undefined }],
    ["another capture", { ...enabledCaps, captureSnapshotId: "old" }],
  ])("does not claim a repair candidate without matching permission: %s", async (_label, caps) => {
    const { client, remote, posts } = setup();
    const dataId = await client.readDeviceDataId!();
    remote.readCapabilities.mockResolvedValue(caps);
    const result = await client.requestAdvice({
      ...request,
      run: { ...request.run!, stage: "repair" },
      deviceRepair: { dataId },
    });
    expect(result).toEqual({ kind: "unavailable", reason: "LLMOPT_VNEXT_DISABLED" });
    expect(deviceWorkReceipt(request.run!.run_id)).toBeUndefined();
    expect(posts).not.toHaveBeenCalled();
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });
  it("replays a total repair from the edited private main after reload", async () => {
    const { client, create, load, remote, posts } = setup();
    const dataId = await client.readDeviceDataId!();
    const candidate: AdviceRequest = {
      ...request,
      run: { ...request.run!, stage: "repair" },
      deviceRepair: { dataId },
      preferenceBundle: {
        contract_version: "llmopt_preference_bundle_v1",
        slots: [],
        prices: [],
        choices: [],
        program: {
          max_total_cost_tenths: 100,
          preferences: [
            { priority: 1, rules: checkedPreferences({ avoid_players: [entry.held[1]] }) },
          ],
        },
      },
    };
    const witness = await client.requestAdvice(candidate);
    if (witness.kind !== "advice") throw new Error("Missing edited primary plan");
    const parent = shownPriorityReference(witness.envelope.payload);
    expect(parent).toBeDefined();
    expect(posts.mock.calls[0]![0].priorityMain).toBe(true);
    expect(posts.mock.calls[0]![0].priorityReference).toBeUndefined();
    const keys = Object.keys(sessionStorage);
    expect(keys.some((key) => key.startsWith("llmopt-device-v1:"))).toBe(false);
    const privateKey = keys.find((key) => key.endsWith(":candidate"))!;
    expect(privateKey).toMatch(/^llmopt-device-repair-v1:/);
    const original = sessionStorage.getItem(privateKey)!;
    const wrong = JSON.parse(original);
    wrong.payload.device_input_fingerprint = "0".repeat(64);
    sessionStorage.setItem(privateKey, JSON.stringify(wrong));
    const replay = { ...candidate, deviceRepair: { dataId, verify: true } };
    const restored = deviceAdviceClient(remote, squad, load, create);
    expect(await restored.requestAdvice(replay)).toMatchObject({ reason: "RUN_BASE_REQUIRED" });
    expect(deviceWorkReceipt(request.run!.run_id)?.repairSelection).toBeUndefined();
    sessionStorage.setItem(privateKey, original);
    const result = await restored.requestAdvice(replay);
    if (result.kind !== "advice") throw new Error("Missing rechecked selection");
    expect(posts.mock.calls[1]![0].priorityReference).toEqual(parent);
    expect(posts.mock.calls[1]![0].priorityMain).toBeUndefined();
    expect(await planIdentity(result.envelope.payload)).toBe(
      await planIdentity(witness.envelope.payload),
    );
    expect(await restored.requestAdvice(replay)).toEqual(result);
    expect(await restored.requestAdvice(candidate)).toEqual(witness);
    expect(deviceWorkReceipt(request.run!.run_id)?.units).toBe(8);
    expect(posts).toHaveBeenCalledTimes(2);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });
  it("rechecks repair support before verifying a selected witness or binding an ordinary cache hit", async () => {
    const { client, remote, posts } = setup();
    const dataId = await client.readDeviceDataId!();
    const ordinary = await client.requestAdvice(request);
    expect(ordinary.kind).toBe("advice");
    const candidate: AdviceRequest = {
      ...request,
      run: { ...request.run!, stage: "repair" },
      deviceRepair: { dataId },
    };
    const afterMain = deviceWorkReceipt(request.run!.run_id);
    remote.readCapabilities.mockResolvedValue({ ...enabledCaps, verifiedRepairs: undefined });
    const disabled = { kind: "unavailable", reason: "LLMOPT_VNEXT_DISABLED" };
    expect(await client.requestAdvice(candidate)).toEqual(disabled);
    expect(deviceWorkReceipt(request.run!.run_id)).toEqual(afterMain);
    remote.readCapabilities.mockResolvedValue(enabledCaps);
    const witness = await client.requestAdvice(candidate);
    expect(witness).toEqual(ordinary);
    const afterWitness = deviceWorkReceipt(request.run!.run_id);
    expect(afterWitness?.repairCandidates).toHaveLength(1);
    expect(afterWitness?.units).toBe(afterMain?.units);
    remote.readCapabilities.mockResolvedValue({ ...enabledCaps, verifiedRepairs: undefined });
    expect(
      await client.requestAdvice({ ...candidate, deviceRepair: { dataId, verify: true } }),
    ).toEqual(disabled);
    expect(deviceWorkReceipt(request.run!.run_id)).toEqual(afterWitness);
    expect(await client.requestAdvice(candidate)).toEqual(witness);
    expect(posts).toHaveBeenCalledTimes(1);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });
  it("pins failed and stale repair attempts to the device and reserves only once", async () => {
    const { client, remote, posts, create, load } = setup();
    const dataId = await client.readDeviceDataId!();
    const missing = {
      ...request,
      deviceRepair: { dataId },
      preferences: checkedPreferences({ include_players: [999999] }),
    };
    const unknown = { kind: "unavailable", reason: "DEVICE_INPUTS_UNAVAILABLE" };
    expect(await client.requestAdvice(missing)).toEqual(unknown);
    const restored = deviceAdviceClient(remote, squad, load, create);
    expect(await restored.requestAdvice(missing)).toEqual(unknown);
    expect(
      await restored.requestAdvice({ ...missing, deviceRepair: { dataId, verify: true } }),
    ).toMatchObject({ reason: "RUN_BASE_REQUIRED" });
    expect(
      await restored.requestAdvice({ ...missing, deviceRepair: { dataId: "0".repeat(64) } }),
    ).toMatchObject({ reason: "RUN_CONTEXT_CHANGED" });
    expect(await restored.requestAdvice({ ...missing, deviceRun: false })).toEqual(unknown);
    expect(await restored.readAdvice({ ...missing, deviceRun: false })).toEqual({
      kind: "not-computed",
    });
    expect(await restored.readPublished(missing)).toEqual({ kind: "not-computed" });
    expect(posts).toHaveBeenCalledTimes(1);
    expect(deviceWorkReceipt(request.run!.run_id)?.units).toBe(4);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
    expect(remote.readAdvice).not.toHaveBeenCalled();
    expect(remote.readPublished).not.toHaveBeenCalled();
  });
  it.each([
    ["Time limit reached", "RUN_BUDGET_EXHAUSTED"],
    ["Iteration limit reached", "RUN_BUDGET_EXHAUSTED"],
    ["Infeasible", "DEVICE_PLAN_FAILED"],
  ])("retains a stopped or failed tie-break as %s", async (status, reason) => {
    let calls = 0;
    const { client } = setup({
      solve(problem, options) {
        if (++calls === 1) return solver.solve(problem, options);
        return { Status: status, ObjectiveValue: 0, Columns: {} };
      },
    });
    const result = await client.requestAdvice(request);
    expect(calls).toBe(2);
    expect(result).toEqual({
      kind: "unavailable",
      reason,
    });
  });
  it("keeps legacy individual pricing inside one device preference execution", async () => {
    const { client, remote, posts } = setup();
    const selection = { preferences: { avoid_players: [entry.held[1]] }, chip: null };
    const bundle: PreferenceBundle = {
      contract_version: "llmopt_preference_bundle_v1",
      program: null,
      slots: [selection],
      prices: [{ outcome: 0, ceiling: null }],
      choices: [
        { accepted: 0, applied: [], selection: null },
        { accepted: 1, applied: [0], selection },
      ],
    };
    const result = await client.requestAdvice({ ...request, preferenceBundle: bundle });
    expect(result.kind).toBe("advice");
    if (result.kind !== "advice") throw new Error("No priced answer.");
    const execution = result.envelope.payload.preference_bundle_result!;
    expect(execution.accepted).toBe(1);
    expect(execution.applied).toEqual([0]);
    expect(execution.components[0]?.status).toBe("done");
    expect(execution.selected?.payload).toEqual(execution.components[0]?.payload);
    expect(posts).toHaveBeenCalledTimes(1);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });
  it("runs three priorities in one device attempt and reloads without remote work", async () => {
    const { client, remote, posts, load, create } = setup();
    const main = await client.requestAdvice(request);
    expect(main.kind).toBe("advice");
    const bundle: PreferenceBundle = {
      contract_version: "llmopt_preference_bundle_v1",
      slots: [],
      prices: [],
      choices: [],
      program: {
        max_total_cost_tenths: 15,
        preferences: [
          { rules: checkedPreferences({ keep_players: [entry.held[0]] }), priority: 1 },
          { rules: checkedPreferences({ avoid_players: [entry.held[1]] }), priority: 2 },
          { rules: checkedPreferences({ keep_players: [entry.held[2]] }), priority: 3 },
        ],
      },
    };
    const followup = {
      ...request,
      deviceRun: true,
      preferenceBundle: bundle,
      run: { ...request.run!, stage: "followup" as const },
    };
    const result = await client.requestAdvice(followup);
    expect(result.kind).toBe("advice");
    if (result.kind !== "advice") throw new Error("No preference execution.");
    const selected = result.envelope.payload.preference_bundle_result?.selected?.payload;
    if (main.kind !== "advice") throw new Error("No confirmed main.");
    const shown = main.envelope.payload;
    expect(posts.mock.calls[1]![0].priorityReference).toEqual({
      squad: [...shown.starting_xi!, ...shown.bench!].map((p) => p.player_id).sort((a, b) => a - b),
      startingXi: shown.starting_xi!.map((p) => p.player_id).sort((a, b) => a - b),
      captain: shown.captain!.player_id,
      proved: true,
    });
    expect(selected?.priority_preferences?.completed_priorities).toEqual([1, 2, 3]);
    expect(selected?.priority_preferences?.total_cost).toBeLessThanOrEqual(1.5);
    expect(selected?.device_input_fingerprint).toBe(
      result.envelope.payload.device_input_fingerprint,
    );
    expect(posts).toHaveBeenCalledTimes(2);
    const reconstructed = deviceAdviceClient(remote, squad, load, create);
    expect(await reconstructed.requestAdvice(followup)).toEqual(result);
    const decisions = posts.mock.calls[1]![0].priorityReference;
    const pinned = {
      ...followup,
      shownDeviceMain: { decisions, fingerprint: shown.device_input_fingerprint! },
    };
    expect(await reconstructed.requestAdvice(pinned)).toEqual(result);
    const stale = { ...pinned, shownDeviceMain: { decisions, fingerprint: "0".repeat(64) } };
    expect(await reconstructed.requestAdvice(stale)).toMatchObject({
      kind: "unavailable",
      reason: "RUN_BASE_REQUIRED",
    });
    expect(posts).toHaveBeenCalledTimes(2);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
    expect((await client.readCapabilities?.(request.leagueId))?.devicePreferenceBundles).toBe(true);
  });
  it("computes hard rules locally and reloads without a server job or another solve", async () => {
    const { client, remote, posts, load, create } = setup();
    const result = await client.requestAdvice(request);
    expect(result.kind).toBe("advice");
    if (result.kind !== "advice") throw new Error("No computed plan.");
    expect(result.source).toBe("device");
    const ids = [...result.envelope.payload.starting_xi!, ...result.envelope.payload.bench!].map(
      (p) => p.player_id,
    );
    expect(ids).toContain(entry.held[0]);
    expect(result.envelope.payload.bank_after_tenths).toBeGreaterThanOrEqual(0);
    expect(posts).toHaveBeenCalledTimes(1);
    const reconstructed = deviceAdviceClient(remote, squad, load, create);
    const reloaded = await reconstructed.readAdvice(request);
    expect(reloaded).toEqual(result);
    expect(posts).toHaveBeenCalledTimes(1);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
    await client.cancelRun?.(request.run!.run_id);
    expect(remote.cancelRun).not.toHaveBeenCalled();
  });
  it("joins duplicate in-flight intent and leaves unsupported windows on the server", async () => {
    const { client, remote, posts } = setup();
    const [first, repeat] = await Promise.all([
      client.requestAdvice(request),
      client.requestAdvice(request),
    ]);
    expect(first).toEqual(repeat);
    expect(posts).toHaveBeenCalledTimes(1);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
    expect((await client.requestAdvice({ ...request, window: 3 })).kind).toBe("unavailable");
    expect(remote.requestAdvice).not.toHaveBeenCalled();
    await client.requestAdvice({
      ...request,
      window: 3,
      run: { ...request.run!, run_id: "e".repeat(32) },
    });
    expect(remote.requestAdvice).toHaveBeenCalledTimes(1);
  });
  it("returns at most three distinct computed plans without another server request", async () => {
    const { client, remote, posts } = setup();
    const result = await client.requestAdvice({ ...request, deviceAlternatives: true });
    expect(result.kind).toBe("advice");
    if (result.kind !== "advice") throw new Error("No computed menu.");
    const plans = [result.envelope.payload, ...(result.envelope.payload.device_alternatives ?? [])];
    expect(plans.length).toBeGreaterThan(1);
    expect(plans.length).toBeLessThanOrEqual(3);
    const decisions = plans.map((plan) =>
      [...plan.starting_xi!, ...plan.bench!]
        .map((player) => player.player_id)
        .sort((a, b) => a - b)
        .join(","),
    );
    expect(new Set(decisions).size).toBe(plans.length);
    expect(posts).toHaveBeenCalledTimes(1);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });

  it("retains the real main across a stalled optional worker, a cache read and a restored tab", async () => {
    const { remote, load } = setup();
    const main = solvePlan(solver, document, entry, () => 0, null, {
      preferences: request.preferences,
    });
    const menu = { ...request, deviceAlternatives: true };
    let notified!: () => void;
    const shown = new Promise<void>((resolve) => {
      notified = resolve;
    });
    const terminate = vi.fn();
    const worker: DeviceSolver = {
      onmessage: null,
      terminate,
      postMessage: ({ id }) =>
        queueMicrotask(() =>
          worker.onmessage?.({
            data: { id, kind: "plan", answer: { ...main, alternatives: [] } },
          } as MessageEvent),
        ),
    };
    const create = vi.fn(() => worker);
    const client = deviceAdviceClient(remote, squad, load, create);
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const response = client.requestAdvice(menu, { onPlan: notified });
      await shown;
      const published = await client.readAdvice(menu);
      expect(published.kind).toBe("advice");
      const restored = deviceAdviceClient(remote, squad, load, create);
      expect(await restored.requestAdvice(menu)).toEqual(published);
      await vi.advanceTimersByTimeAsync(14_999);
      expect(terminate).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      expect(await response).toEqual(published);
      expect(terminate).toHaveBeenCalledTimes(1);
      expect(create).toHaveBeenCalledTimes(1);
      expect(remote.requestAdvice).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
  it("delivers already reserved work when receipt storage closes but refuses another solve", async () => {
    const { remote, load } = setup();
    const main = solvePlan(solver, document, entry, () => 0, null, {
      preferences: request.preferences,
    });
    const menu = { ...request, deviceAlternatives: true };
    const id = request.run!.run_id;
    let started!: (id: number) => void;
    const posted = new Promise<number>((resolve) => {
      started = resolve;
    });
    const worker: DeviceSolver = {
      onmessage: null,
      terminate: vi.fn(),
      postMessage: (input) => started(input.id),
    };
    const create = vi.fn(() => worker);
    const client = deviceAdviceClient(remote, squad, load, create);
    expect(await client.prepareDeviceRun!(menu)).toBe(true);
    expect(deviceWorkReceipt(id)?.units).toBe(0);
    const onPlan = vi.fn();
    const result = client.requestAdvice(menu, { onPlan });
    const workerId = await posted;
    const receipt = deviceWorkReceipt(id)!;
    expect(receipt.units).toBe(4);
    const key = "llmopt-device-work-v1:" + id;
    const getItem = Storage.prototype.getItem;
    const unreadable = vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (
      this: Storage,
      name,
    ) {
      if (name === key) throw new DOMException("Storage unavailable", "SecurityError");
      return getItem.call(this, name);
    });
    worker.onmessage?.({
      data: { id: workerId, kind: "plan", answer: { ...main, alternatives: [] } },
    } as MessageEvent);
    expect(onPlan).toHaveBeenCalledOnce();
    const shown = onPlan.mock.calls[0]![0];
    expect(shown.kind).toBe("advice");
    worker.onerror?.(new Error("Optional search failed"));
    expect(await result).toEqual(shown);
    expect(await client.requestAdvice(menu)).toEqual(shown);
    expect(await client.requestAdvice(request)).toEqual({
      kind: "unavailable",
      reason: "RUN_STORE_UNAVAILABLE",
    });
    unreadable.mockRestore();
    expect(deviceWorkReceipt(id)).toEqual(receipt);
    sessionStorage.setItem(key, JSON.stringify({ ...receipt, binding: "another capture" }));
    expect(await client.requestAdvice(menu)).toEqual({
      kind: "unavailable",
      reason: "RUN_CONTEXT_CHANGED",
    });
    sessionStorage.setItem(key, JSON.stringify({ ...receipt, closed: true }));
    expect(await client.requestAdvice(menu)).toEqual({
      kind: "unavailable",
      reason: "RUN_CANCELLED",
    });
    expect(create).toHaveBeenCalledTimes(1);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });
  it("uses the public entry's release setting for a local one-week plan", async () => {
    const { remote, create, load } = setup();
    const forwarded = { ...squad, league_id: 0 };
    const client = deviceAdviceClient(remote, forwarded, load, create);
    expect(
      (await client.readPublicCapabilities?.(0, squad.entry.entry_id))?.strategies["saf-puan"]
        ?.windows,
    ).toEqual([1]);
    const result = await client.requestAdvice({ ...request, leagueId: 0, publicEntry: true });
    expect(result.kind).toBe("advice");
    if (result.kind === "advice") expect(result.envelope.payload.league_id).toBe(0);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
    expect(remote.readPublicCapabilities).toHaveBeenCalledWith(0, squad.entry.entry_id, {
      signal: expect.anything(),
    });
    expect(remote.readCapabilities).not.toHaveBeenCalled();
  });
  it.each([
    ["no response", null],
    ["missing release", publicEntryCapabilities(squad)],
    ["disabled release", { ...enabledCaps, llmoptVNext: false }],
    ["old capture", { ...enabledCaps, captureSnapshotId: "old", devicePreferenceBundles: true }],
    ["another gameweek", { ...enabledCaps, gameweek: squad.gameweek + 1 }],
  ])("does not advertise or start a local alternative with %s", async (_label, capabilities) => {
    const { client, remote, posts } = setup();
    remote.readCapabilities.mockResolvedValue(capabilities);
    expect(
      (await client.readCapabilities!(request.leagueId))?.devicePreferenceBundles,
    ).toBeUndefined();
    expect(await client.requestAdvice({ ...request, deviceAlternatives: true })).toMatchObject({
      kind: "unavailable",
      reason: "LLMOPT_VNEXT_DISABLED",
    });
    expect(deviceWorkReceipt(request.run!.run_id)).toBeUndefined();
    expect(posts).not.toHaveBeenCalled();
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });
  it("reads a saved session after rollback and refuses new work with the same run", async () => {
    const { client, remote, posts, load, create } = setup();
    const answer = await client.requestAdvice(request);
    expect(answer.kind).toBe("advice");
    const receipt = deviceWorkReceipt(request.run!.run_id);
    expect(receipt!.units).toBeGreaterThan(0);
    remote.readCapabilities.mockRejectedValue(new Error("offline"));
    const restored = deviceAdviceClient(remote, squad, load, create);
    expect(await restored.readAdvice(request)).toEqual(answer);
    expect(await restored.requestAdvice(request)).toEqual(answer);
    const next = await restored.requestAdvice({ ...request, deviceAlternatives: true });
    expect(next).toEqual({ kind: "unavailable", reason: "LLMOPT_VNEXT_DISABLED" });
    expect(deviceWorkReceipt(request.run!.run_id)).toEqual(receipt);
    expect(posts).toHaveBeenCalledTimes(1);
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });
  it("shares an in-flight capability read and cancels before starting the worker", async () => {
    const { client, remote, posts } = setup();
    let resolve!: (value: typeof enabledCaps) => void;
    remote.readCapabilities.mockReturnValue(
      new Promise((accept) => {
        resolve = accept;
      }),
    );
    const capability = client.readCapabilities!(request.leagueId);
    const calculation = client.requestAdvice(request);
    await vi.waitFor(() => expect(remote.readCapabilities).toHaveBeenCalledTimes(1));
    await client.cancelRun!(request.run!.run_id);
    resolve(enabledCaps);
    expect((await capability)?.devicePreferenceBundles).toBe(true);
    expect(await calculation).toEqual({ kind: "unavailable", reason: "RUN_CANCELLED" });
    expect(remote.readCapabilities).toHaveBeenCalledTimes(1);
    expect(deviceWorkReceipt(request.run!.run_id)).toBeUndefined();
    expect(posts).not.toHaveBeenCalled();
  });
  it("rejects another capture before starting a worker", async () => {
    const { remote, posts, create, load } = setup();
    const client = deviceAdviceClient(
      remote,
      squad,
      async () => ({
        ...(await load()),
        payload: { ...document, source_snapshot_id: "obsolete" },
      }),
      create,
    );
    expect((await client.requestAdvice(request)).kind).toBe("unavailable");
    expect(posts).not.toHaveBeenCalled();
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });
  it("starts no worker when durable capacity cannot be recorded", async () => {
    const { client, remote, posts } = setup();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(await client.prepareDeviceRun?.(request)).toBe(false);
    const result = await client.requestAdvice(request);
    expect(result).toMatchObject({ kind: "unavailable", reason: "RUN_STORE_UNAVAILABLE" });
    expect(posts).not.toHaveBeenCalled();
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });
  it("binds the confirmed inputs without starting or reserving a worker", async () => {
    const { client, posts, remote } = setup();
    expect(await client.prepareDeviceRun?.(request)).toBe(true);
    expect(deviceWorkReceipt(request.run!.run_id)).toMatchObject({ units: 0, closed: false });
    expect(posts).not.toHaveBeenCalled();
    expect(remote.requestAdvice).not.toHaveBeenCalled();
    expect((await client.requestAdvice(request)).kind).toBe("advice");
    expect(deviceWorkReceipt(request.run!.run_id)?.units).toBe(4);
  });
  it("keeps server work and cancellation usable when session storage is blocked", async () => {
    const { client, remote, posts } = setup();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const server = {
      ...request,
      window: 3 as const,
      deviceRun: false,
      run: { ...request.run!, run_id: "e".repeat(32) },
    };
    await expect(client.requestAdvice(server)).resolves.toEqual({ kind: "unavailable" });
    expect(remote.requestAdvice).toHaveBeenCalledTimes(1);
    await client.cancelRun?.(server.run.run_id);
    expect(remote.cancelRun).toHaveBeenCalledWith(server.run.run_id);
    expect(posts).not.toHaveBeenCalled();
  });
});
