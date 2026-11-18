import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { webcrypto } from "node:crypto";
import { beforeAll, beforeEach, afterEach, describe, it, expect, vi } from "vitest";
import fixture from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { checkedPreferences } from "../advice/decisionPreferences";
import type { AdviceClient, AdviceRequest } from "../advice/adviceClient";
import { deviceAdviceClient } from "./adviceClient";
import { replyTo } from "./replies";
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
function setup() {
  const remote = {
    readAdvice: vi.fn().mockResolvedValue({ kind: "not-computed" }),
    readPublished: vi.fn().mockResolvedValue({ kind: "not-computed" }),
    requestAdvice: vi.fn().mockResolvedValue({ kind: "unavailable" }),
    readJob: vi.fn(),
    cancelRun: vi.fn(),
    readCapabilities: vi.fn().mockResolvedValue(null),
  } satisfies AdviceClient;
  const posts = vi.fn();
  const create = () => {
    const worker: DeviceSolver = {
      onmessage: null,
      terminate: vi.fn(),
      postMessage: (input) => {
        posts(input);
        queueMicrotask(() =>
          replyTo(solver, input, (data) => worker.onmessage?.({ data } as MessageEvent)),
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
  it("has local one-week capabilities for an unpublished league", async () => {
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
    const result = await client.requestAdvice(request);
    expect(result).toMatchObject({ kind: "unavailable", reason: "RUN_STORE_UNAVAILABLE" });
    expect(posts).not.toHaveBeenCalled();
    expect(remote.requestAdvice).not.toHaveBeenCalled();
  });
});
