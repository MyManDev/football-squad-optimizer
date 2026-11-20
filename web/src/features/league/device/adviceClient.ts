/** Advice transport for verified one-week device rules; credentials never enter it. */
import type { AdviceClient, AdviceRequest, AdviceReadResult } from "../advice/adviceClient";
import { checkedAdvice } from "../advice/adviceResponse";
import { capabilitiesForPage, type AdviceCapabilities } from "../advice/adviceCapabilities";
import { withRequestDeadline, type RequestOptions } from "../../../data/request";
import { preferencesKey } from "../advice/decisionPreferences";
import { bundleKey } from "../advice/preferenceBundle";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { deviceAdviceEnvelope } from "./deviceAdvice";
import { deviceSelection } from "./selection";
import { isDevicePlanDocument, isDevicePlanEntry, type DevicePlanDocument } from "./types";
import type { DeviceSolver } from "./useDevicePlan";
import {
  reserveDeviceWork,
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
  const pending = new Map<string, Promise<AdviceReadResult>>();
  const capabilityReads = new Map<string, Promise<AdviceCapabilities | null>>();
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
      const bytes = new TextEncoder().encode(
        JSON.stringify({ document, entry: squad.device_plan }),
      );
      const hash = await crypto.subtle.digest("SHA-256", bytes);
      const fingerprint = Array.from(new Uint8Array(hash), (b) =>
        b.toString(16).padStart(2, "0"),
      ).join("");
      return { document, fingerprint };
    })().catch((error) => {
      published = undefined;
      throw error;
    }));
  const withLocal = (remoteCaps: AdviceCapabilities | null): AdviceCapabilities | null => {
    const caps = capabilitiesForPage(remoteCaps, {
      leagueId: squad.league_id,
      season: squad.season,
      gameweek: squad.gameweek,
      snapshotId: squad.source_snapshot_id,
    });
    if (caps?.llmoptVNext !== true || !consistentBlock || !squad.source_snapshot_id) return caps;
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
  const readCapabilities = (leagueId: number, entryId?: number, options?: RequestOptions) =>
    withRequestDeadline(async () => {
      const key = JSON.stringify([leagueId, entryId ?? null]);
      let read = capabilityReads.get(key);
      if (!read) {
        // A dismissed view cannot cancel a concurrent confirmation's read. The
        // underlying HTTP call keeps its own timeout. Only concurrent reads share it.
        read = withRequestDeadline(async (signal) => {
          const remoteCaps =
            entryId === undefined
              ? await remote.readCapabilities?.(leagueId, { signal })
              : await remote.readPublicCapabilities?.(leagueId, entryId, { signal });
          return withLocal(remoteCaps ?? null);
        })
          .catch(() => null)
          .finally(() => capabilityReads.delete(key));
        capabilityReads.set(key, read);
      }
      return read;
    }, options);
  const eligible = (request: AdviceRequest) =>
    request.run !== undefined &&
    request.deviceRun !== false &&
    squad.source_snapshot_id !== null &&
    consistentBlock &&
    request.leagueId === squad.league_id &&
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
  const cached = (request: AdviceRequest, fingerprint: string): AdviceReadResult => {
    const address = key(request, fingerprint);
    const held = memory.get(address);
    if (held) return held;
    try {
      const raw = globalThis.sessionStorage?.getItem(address);
      if (raw) {
        const envelope = checkedAdvice(JSON.parse(raw), request);
        if (envelope.payload.source_snapshot_id === squad.source_snapshot_id) {
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
  const abort = () => new DOMException("The device request ended.", "AbortError");
  return {
    localRequestAllowanceMs: (request) =>
      eligible(request)
        ? (DEVICE_LOAD_ALLOWANCE_SECONDS +
            DEVICE_REPLY_GRACE_SECONDS +
            DEVICE_SOLVE_CEILING_SECONDS) *
          1000
        : undefined,
    readPublished: (request, options) => remote.readPublished(request, options),
    readJob: (id, options) => remote.readJob(id, options),
    readCapabilities: (id, options) => readCapabilities(id, undefined, options),
    readPublicCapabilities: (id, entry, options) => readCapabilities(id, entry, options),
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
      if (!eligible(request)) return remote.readAdvice(request, options);
      try {
        return cached(request, (await verified()).fingerprint);
      } catch {
        return { kind: "not-computed" };
      }
    },
    requestAdvice: async (request, options) => {
      if (
        !request.run &&
        (request.deviceRun || request.deviceAlternatives || request.preferenceBundle)
      )
        return { kind: "unavailable", reason: "RUN_ID_REQUIRED" };
      if (request.run && closedLocalRuns.has(request.run.run_id))
        return { kind: "unavailable", reason: "RUN_CANCELLED" };
      if (!eligible(request)) {
        if (request.deviceRun === true || request.deviceAlternatives === true)
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
        inputs = await verified();
      } catch {
        return { kind: "unavailable", reason: "DEVICE_INPUTS_UNAVAILABLE" };
      }
      const saved = cached(request, inputs.fingerprint);
      const binding = JSON.stringify([
        inputs.fingerprint,
        request.leagueId,
        request.entryId,
        request.window,
      ]);
      if (saved.kind === "advice") {
        try {
          if (request.run && deviceWorkReceipt(request.run.run_id))
            bindDeviceRun(request.run.run_id, binding);
        } catch (error) {
          return {
            kind: "unavailable",
            reason: error instanceof DeviceWorkRefused ? error.code : "DEVICE_PLAN_FAILED",
          };
        }
        return saved;
      }
      const address = key(request, inputs.fingerprint);
      const runningKey = address + ":" + (request.run?.run_id ?? "");
      let work = pending.get(runningKey);
      if (!work) {
        work = (async (): Promise<AdviceReadResult> => {
          const document = inputs.document;
          const caps = await readCapabilities(
            request.leagueId,
            request.publicEntry ? request.entryId : undefined,
            options,
          );
          if (caps?.llmoptVNext !== true || caps.devicePreferenceBundles !== true)
            throw new DeviceWorkRefused("LLMOPT_VNEXT_DISABLED");
          if (options?.signal?.aborted) throw abort();
          if (request.run && closedLocalRuns.has(request.run.run_id))
            throw new DeviceWorkRefused("RUN_CANCELLED");
          reserveDeviceWork(request.run?.run_id, binding);
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
                () => finish(new Error("Device solve did not complete.")),
                (DEVICE_LOAD_ALLOWANCE_SECONDS +
                  DEVICE_REPLY_GRACE_SECONDS +
                  DEVICE_SOLVE_CEILING_SECONDS) *
                  1000,
              );
              options?.signal?.addEventListener("abort", cancelled, { once: true });
              worker.onmessage = ({ data }) => {
                if (data.id !== id || data.kind === "ready") return;
                if (data.kind === "answer") finish(undefined, data.answer);
                else finish(new Error("Device solve did not prove this selection."));
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
          memory.set(address, result);
          try {
            globalThis.sessionStorage?.setItem(address, JSON.stringify(envelope));
          } catch {
            /* Memory remains usable. */
          }
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
        if (options?.signal?.aborted) throw error;
        return {
          kind: "unavailable",
          reason: error instanceof DeviceWorkRefused ? error.code : "DEVICE_PLAN_FAILED",
        };
      }
    },
  };
}
