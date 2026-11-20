/** Advice transport for verified one-week device rules; credentials never enter it. */
import type {
  AdviceClient,
  AdviceRequest,
  AdviceReadResult,
  AdviceRequestResult,
} from "../advice/adviceClient";
import { checkedAdvice } from "../advice/adviceResponse";
import type { AdviceCapabilities } from "../advice/adviceCapabilities";
import { preferencesKey } from "../advice/decisionPreferences";
import { bundleKey } from "../advice/preferenceBundle";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { deviceAdviceEnvelope } from "./deviceAdvice";
import { deviceSelection } from "./selection";
import { isDevicePlanDocument, isDevicePlanEntry, type DevicePlanDocument } from "./types";
import type { DeviceSolver } from "./useDevicePlan";
import {
  reserveDeviceWork,
  claimDeviceRepair,
  bindDeviceRun,
  closeDeviceWork,
  deviceWorkReceipt,
  DeviceWorkRefused,
} from "./workBudget";
import {
  DEVICE_LOAD_ALLOWANCE_SECONDS,
  DEVICE_REPLY_GRACE_SECONDS,
  DEVICE_SOLVE_CEILING_SECONDS,
} from "./solve/ceiling";

function repairRequest(request: AdviceRequest) {
  return (
    request.deviceRepair !== undefined || (request.window === 1 && request.run?.stage === "repair")
  );
}

async function sha256(value: string) {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function refused(reason: string): AdviceRequestResult {
  return {
    kind: "unavailable",
    reason,
    ...(reason === "PLAN_NOT_FOUND" ? { infeasibility: { repairs: [] } } : {}),
  };
}

export function deviceAdviceClient(
  remote: AdviceClient,
  squad: EntrySquad,
  load: () => Promise<LeagueViewEnvelope<DevicePlanDocument>>,
  createSolver: () => DeviceSolver = () =>
    new Worker(new URL("./deviceSolver.worker.ts", import.meta.url), {
      type: "module",
    }) as unknown as DeviceSolver,
): AdviceClient {
  const memory = new Map<string, AdviceReadResult>();
  const failures = new Map<string, string>();
  const pending = new Map<string, Promise<AdviceReadResult>>();
  const localRuns = new Set<string>();
  const closedLocalRuns = new Set<string>();
  const block = squad.device_plan;
  const owned = new Set([...squad.starting_xi, ...squad.bench].map((player) => player.player_id));
  const consistentBlock =
    isDevicePlanEntry(block) &&
    owned.size === block.held.length &&
    block.held.every((id) => owned.has(id)) &&
    block.bank_tenths === squad.bank_tenths &&
    (!squad.free_transfers_known || block.free_transfers === squad.free_transfers);
  let sequence = 0;
  let published: Promise<{ document: DevicePlanDocument; fingerprint: string }> | undefined;
  const verified = () =>
    (published ??= (async () => {
      const document = (await load()).payload;
      if (
        !isDevicePlanDocument(document) ||
        document.source_snapshot_id !== squad.source_snapshot_id ||
        document.season !== squad.season ||
        document.gameweek !== squad.gameweek
      )
        throw new Error("The device inputs do not match the requested capture.");
      const roster = new Set(document.players.map(({ id }) => id));
      if (!block || !block.held.every((id) => roster.has(id)))
        throw new Error("A held player is missing from the device projections.");
      const fingerprint = await sha256(JSON.stringify({ document, entry: squad.device_plan }));
      return { document, fingerprint };
    })().catch((error) => {
      published = undefined;
      throw error;
    }));
  const withLocal = (caps: AdviceCapabilities | null): AdviceCapabilities | null => {
    if (caps?.llmoptVNext !== true || !consistentBlock || !squad.source_snapshot_id) return caps;
    if (caps.captureSnapshotId !== squad.source_snapshot_id) return caps;
    return {
      ...caps,
      preferences: true,
      devicePreferenceBundles: true,
      strategies: {
        ...caps.strategies,
        "saf-puan": {
          requiresRival: false,
          windows: caps.preferences
            ? [...new Set([1 as const, ...(caps.strategies["saf-puan"]?.windows ?? [])])]
            : [1],
        },
      },
    };
  };
  const eligible = (request: AdviceRequest) =>
    request.deviceRun !== false &&
    squad.source_snapshot_id !== null &&
    consistentBlock &&
    request.entryId === squad.entry.entry_id &&
    (request.season === undefined || request.season === squad.season) &&
    (request.gameweek === undefined || request.gameweek === squad.gameweek) &&
    deviceSelection(request, squad)?.kind === "plain";
  const key = (request: AdviceRequest, fingerprint: string) =>
    "llmopt-device-v1:" +
    JSON.stringify([
      squad.source_snapshot_id,
      fingerprint,
      request.leagueId,
      request.entryId,
      request.strategy,
      request.window,
      request.deviceRun ?? true,
      request.deviceAlternatives ?? false,
      request.chip ?? null,
      preferencesKey(request.preferences),
      ...(request.preferenceBundle ? [bundleKey(request.preferenceBundle)] : []),
    ]);
  const cached = (
    request: AdviceRequest,
    fingerprint: string,
    address = key(request, fingerprint),
  ): AdviceReadResult => {
    const held = memory.get(address);
    if (held) return held;
    try {
      const raw = globalThis.sessionStorage?.getItem(address);
      if (raw) {
        const envelope = checkedAdvice(JSON.parse(raw), request);
        if (envelope.payload.source_snapshot_id === squad.source_snapshot_id) {
          envelope.payload.device_input_fingerprint = fingerprint;
          for (const option of envelope.payload.device_alternatives ?? [])
            option.device_input_fingerprint = fingerprint;
          const result: AdviceReadResult = { kind: "advice", envelope, source: "device" };
          memory.set(address, result);
          return result;
        }
      }
    } catch {
      /* Recompute an unreadable cached answer on the device. */
    }
    return { kind: "not-computed" };
  };
  function remember(address: string, result: Extract<AdviceReadResult, { kind: "advice" }>) {
    memory.set(address, result);
    try {
      globalThis.sessionStorage.setItem(address, JSON.stringify(result.envelope));
    } catch {
      /* A persisted capacity claim still prevents another attempt after reload. */
    }
  }
  const abort = () => new DOMException("The device request ended.", "AbortError");
  return {
    readDeviceDataId: async () => {
      published = undefined;
      return (await verified()).fingerprint;
    },
    localRequestAllowanceMs: (request) =>
      eligible(request)
        ? (DEVICE_LOAD_ALLOWANCE_SECONDS +
            DEVICE_REPLY_GRACE_SECONDS +
            DEVICE_SOLVE_CEILING_SECONDS) *
          1000
        : undefined,
    readPublished: (request, options) =>
      repairRequest(request)
        ? Promise.resolve({ kind: "not-computed" })
        : remote.readPublished(request, options),
    readJob: (id, options) => remote.readJob(id, options),
    readCapabilities: async (id, options) =>
      withLocal((await remote.readCapabilities?.(id, options)) ?? null),
    readPublicCapabilities: async (id, entry, options) =>
      withLocal((await remote.readPublicCapabilities?.(id, entry, options)) ?? null),
    cancelRun: async (id) => {
      let local = localRuns.has(id);
      try {
        local = closeDeviceWork(id) || local;
      } catch {
        // An unavailable local receipt must not prevent cancelling a server job.
      }
      if (local) closedLocalRuns.add(id);
      else await remote.cancelRun?.(id);
    },
    readAdvice: async (request, options) => {
      // Only requestAdvice can check the selection receipt and distinguish a verified replay
      // from an ordinary cached plan at the very same computation address.
      if (repairRequest(request)) return { kind: "not-computed" };
      if (!eligible(request)) return remote.readAdvice(request, options);
      try {
        return cached(request, (await verified()).fingerprint);
      } catch {
        return { kind: "not-computed" };
      }
    },
    requestAdvice: async (request, options) => {
      const repair = repairRequest(request);
      const verify = request.deviceRepair?.verify === true;
      if (request.run && closedLocalRuns.has(request.run.run_id))
        return { kind: "unavailable", reason: "RUN_CANCELLED" };
      if (!eligible(request)) {
        if (repair) return refused("DEVICE_INPUTS_UNAVAILABLE");
        if (request.deviceRun === true)
          return { kind: "unavailable", reason: "RUN_CONTEXT_CHANGED" };
        if (request.run) {
          if (localRuns.has(request.run.run_id))
            return { kind: "unavailable", reason: "RUN_CONTEXT_CHANGED" };
          if (request.deviceRun !== false) {
            try {
              if (deviceWorkReceipt(request.run.run_id))
                return { kind: "unavailable", reason: "RUN_CONTEXT_CHANGED" };
            } catch {
              /* Unavailable device storage does not disable server work. */
            }
          }
        }
        return remote.requestAdvice(request, options);
      }
      if (options?.signal?.aborted) throw abort();
      if (request.run) localRuns.add(request.run.run_id);
      let inputs: Awaited<ReturnType<typeof verified>>;
      try {
        if (repair) published = undefined;
        inputs = await verified();
      } catch {
        return { kind: "unavailable", reason: "DEVICE_INPUTS_UNAVAILABLE" };
      }
      if (request.deviceRepair && request.deviceRepair.dataId !== inputs.fingerprint)
        return refused("RUN_CONTEXT_CHANGED");
      const binding = JSON.stringify([
        inputs.fingerprint,
        request.leagueId,
        request.entryId,
        request.window,
      ]);
      try {
        bindDeviceRun(request.run?.run_id, binding);
      } catch (error) {
        return {
          kind: "unavailable",
          reason: error instanceof DeviceWorkRefused ? error.code : "DEVICE_PLAN_FAILED",
        };
      }
      const saved = cached(request, inputs.fingerprint);
      if (!repair && saved.kind === "advice") return saved;
      const address = key(request, inputs.fingerprint);
      const addressDigest = repair ? await sha256(address) : undefined;
      const repairKey =
        addressDigest && `llmopt-device-repair-v1:${request.run!.run_id}:${addressDigest}`;
      const privateKey = repairKey && repairKey + (verify ? ":selection" : ":candidate");
      const runningKey = privateKey || address + ":" + (request.run?.run_id ?? "");
      let claimed = false;
      let work = pending.get(runningKey);
      if (!work) {
        work = (async (): Promise<AdviceReadResult> => {
          const document = inputs.document;
          if (options?.signal?.aborted) throw abort();
          if (addressDigest && privateKey) {
            if (
              verify &&
              cached(request, inputs.fingerprint, repairKey + ":candidate").kind !== "advice"
            )
              throw new DeviceWorkRefused("RUN_BASE_REQUIRED");
            const useSaved = !verify && saved.kind === "advice";
            claimed = claimDeviceRepair(
              request.run!.run_id,
              binding,
              addressDigest,
              verify,
              useSaved,
            );
            if (!claimed) {
              const repeated = cached(request, inputs.fingerprint, privateKey);
              if (repeated.kind === "advice") return repeated;
              let reason = failures.get(privateKey);
              if (!reason) {
                try {
                  reason = globalThis.sessionStorage.getItem(privateKey + ":failure") ?? undefined;
                } catch {
                  throw new DeviceWorkRefused("RUN_STORE_UNAVAILABLE");
                }
              }
              throw new DeviceWorkRefused(reason ?? "RUN_BUDGET_EXHAUSTED");
            }
            if (useSaved) {
              remember(privateKey, saved);
              return saved;
            }
          } else reserveDeviceWork(request.run?.run_id, binding);
          const worker = createSolver();
          const id = ++sequence;
          const answer = await new Promise<Parameters<typeof deviceAdviceEnvelope>[2]>(
            (resolve, reject) => {
              const finish = (
                error?: unknown,
                value?: Parameters<typeof deviceAdviceEnvelope>[2],
              ) => {
                clearTimeout(timer);
                options?.signal?.removeEventListener("abort", cancelled);
                worker.terminate();
                if (error) reject(error);
                else resolve(value!);
              };
              const cancelled = () => finish(abort());
              const timer = setTimeout(
                () => finish(new DeviceWorkRefused("RUN_BUDGET_EXHAUSTED")),
                (DEVICE_LOAD_ALLOWANCE_SECONDS +
                  DEVICE_REPLY_GRACE_SECONDS +
                  DEVICE_SOLVE_CEILING_SECONDS) *
                  1000,
              );
              options?.signal?.addEventListener("abort", cancelled, { once: true });
              worker.onmessage = ({ data }) => {
                if (data.id !== id || data.kind === "ready") return;
                if (data.kind === "answer") finish(undefined, data.answer);
                else if (data.kind === "refused" && data.primaryInfeasible)
                  finish(new DeviceWorkRefused("PLAN_NOT_FOUND"));
                else if (data.kind === "refused" && data.status === "Time limit reached")
                  finish(new DeviceWorkRefused("RUN_BUDGET_EXHAUSTED"));
                else if (data.kind === "failed" && data.inputsUnavailable)
                  finish(new DeviceWorkRefused("DEVICE_INPUTS_UNAVAILABLE"));
                else finish(new DeviceWorkRefused("DEVICE_PLAN_FAILED"));
              };
              worker.onerror = () => finish(new Error("The device solve failed."));
              worker.postMessage({
                id,
                document,
                ...(request.deviceAlternatives ? { alternatives: true } : {}),
                entry: squad.device_plan!,
                ...(request.preferences ? { preferences: request.preferences } : {}),
                ...(request.preferenceBundle ? { preferenceBundle: request.preferenceBundle } : {}),
              });
            },
          );
          if (
            request.run &&
            (closedLocalRuns.has(request.run.run_id) ||
              deviceWorkReceipt(request.run.run_id)?.closed)
          )
            throw new DeviceWorkRefused("RUN_CANCELLED");
          const envelope = checkedAdvice(
            deviceAdviceEnvelope(document, squad, answer, new Date(), request.leagueId),
            request,
          );
          const stamp = (payload: typeof envelope.payload) => {
            payload.device_input_fingerprint = inputs.fingerprint;
            payload.device_alternatives?.forEach(stamp);
            const bundle = payload.preference_bundle_result;
            for (const component of [...(bundle?.components ?? []), bundle?.selected])
              if (component?.payload) stamp(component.payload);
          };
          stamp(envelope.payload);
          const result: AdviceReadResult = { kind: "advice", envelope, source: "device" };
          if (privateKey) remember(privateKey, result);
          if (!verify) remember(address, result);
          return result;
        })().finally(() => pending.delete(runningKey));
        pending.set(runningKey, work);
      }
      try {
        const result = await work;
        return result.kind === "advice"
          ? result
          : { kind: "unavailable", reason: "DEVICE_PLAN_FAILED" };
      } catch (error) {
        const reason = error instanceof DeviceWorkRefused ? error.code : "DEVICE_PLAN_FAILED";
        if (claimed && privateKey) {
          failures.set(privateKey, reason);
          try {
            globalThis.sessionStorage.setItem(privateKey + ":failure", reason);
          } catch {
            /* The capacity claim remains durable. */
          }
        }
        if (options?.signal?.aborted) throw error;
        return refused(reason);
      }
    },
  };
}
