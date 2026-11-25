import { describe, expect, it, vi } from "vitest";
import fixture from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { publicEntryCapabilities } from "../advice/adviceCapabilities";
import type { DevicePlanEntry } from "../device/types";
import { preparePlans, type PlanDraft } from "./intent";
import { baseDraft, prepareRun, requestFor, restoreRun } from "./planRun";
import { prepareCombined } from "./combinedPlan";
import { prepareConfirmedRun } from "./releaseRun";

const squad = {
  ...mockEntrySquadEnvelopes[35249001]!.payload,
  device_plan: fixture.members[0]!.entry as unknown as DevicePlanEntry,
};
const held = new Set([...squad.starting_xi, ...squad.bench].map((p) => p.player_id));
const draft: PlanDraft = { hard: [], soft: [], window: 1 };
const read = (window: 1 | 3 | 5) => requestFor(squad, false, window, true);
const confirmation = { runId: "a".repeat(32), wildcardNotHeld: false };
describe("pinned execution route", () => {
  it("pins a cold one-week request to the server until device execution is granted", () => {
    expect(requestFor(squad, false, 1)).toMatchObject({
      deviceRun: false,
      deviceAlternatives: false,
    });
    expect(read(1)).toMatchObject({ deviceRun: true, deviceAlternatives: true });
    expect(read(3).deviceRun).toBe(false);
  });
  it("never resumes an unbound device marker as a new device run", () => {
    const restored = restoreRun(
      {
        draft,
        confirmation: { wildcardNotHeld: false, deviceRun: true, deviceAlternatives: true },
      },
      held,
      read,
    );
    expect(restored?.baseRequest).toMatchObject({ deviceRun: false, deviceAlternatives: false });
  });
  it("keeps a legacy confirmed server run on the server when device inputs appear", () => {
    expect(read(1).deviceRun).toBe(true);
    const restored = restoreRun({ draft, confirmation }, held, read);
    expect(restored?.baseRequest?.deviceRun).toBe(false);
    expect(restored?.baseRequest?.deviceAlternatives).toBe(false);
    expect(restored?.baseRequest?.preferences.net_points_priority).not.toBe(true);
  });
  it("restores the same device objective and menu", () => {
    const restored = restoreRun(
      { draft, confirmation: { ...confirmation, deviceRun: true, deviceAlternatives: true } },
      held,
      read,
    );
    expect(restored?.baseRequest?.deviceRun).toBe(true);
    expect(restored?.baseRequest?.deviceAlternatives).toBe(true);
    expect(restored?.baseRequest?.preferences.net_points_priority).toBe(true);
  });
  it("keeps the entire preference run on the service for an unverified chip", () => {
    const preferred: PlanDraft = { ...draft, soft: [{ kind: "wildcard" }] };
    const run = prepareRun({
      draft: preferred,
      held,
      request: read(1),
      plans: preparePlans(baseDraft(preferred), held),
      wildcardNotHeld: false,
    });
    expect(run.baseRequest?.deviceRun).toBe(false);
    expect(run.slots.every((slot) => slot.request?.deviceRun === false)).toBe(true);
    expect(prepareCombined(run, [0]).request?.deviceRun).toBe(false);
  });
});

describe("the confirmed workflow shared with the acceptance workload", () => {
  const inputs = { draft, held, plans: preparePlans(draft, held) };
  const capabilities = { ...publicEntryCapabilities(squad), preferences: true };
  const runId = confirmation.runId;

  it.each([
    [3, true, true, false, false, false],
    [3, true, true, true, false, false],
    [3, true, true, false, true, true],
    [3, true, true, true, true, true],
    [3, true, false, true, true, false],
    [3, false, false, true, true, false],
    [3, false, true, true, true, false],
    [1, true, false, true, true, false],
  ] as const)(
    "prepares the %i-week path mode with master=%s, three weeks=%s, packages=%s and paths=%s",
    async (window, master, threeWeek, packages, paths, expected) => {
      const requestDraft = { ...draft, window };
      const run = await prepareConfirmedRun(
        { draft: requestDraft, held, plans: preparePlans(requestDraft, held) },
        squad,
        false,
        {
          ...capabilities,
          strategies: { "saf-puan": { windows: [1, 3], requiresRival: false } },
          ...(master ? { llmoptVNext: true } : {}),
          ...(threeWeek ? { llmoptVNextThreeWeek: true } : {}),
          ...(packages ? { transferPackages: true } : {}),
          ...(paths ? { threeWeekPaths: true } : {}),
        },
        runId,
        undefined,
      );
      expect(run?.baseRequest?.window).toBe(window);
      expect(run?.inputs.paths3w).toBe(expected ? true : undefined);
      expect(run?.baseRequest?.run?.run_id).toBe(
        master && (window === 1 || threeWeek) ? runId : undefined,
      );
    },
  );

  it("uses the current master and device grant together when choosing a one-week menu", async () => {
    const localSupport = { ...capabilities, devicePreferenceBundles: true as const };
    const bind = vi.fn(async () => true);
    const legacy = await prepareConfirmedRun(inputs, squad, false, localSupport, runId, bind);
    expect(legacy?.baseRequest).not.toHaveProperty("run");
    expect(legacy?.baseRequest?.deviceRun).toBe(false);
    const server = await prepareConfirmedRun(
      inputs,
      squad,
      false,
      { ...capabilities, llmoptVNext: true },
      runId,
      bind,
    );
    expect(server?.baseRequest).toMatchObject({
      run: { run_id: runId, stage: "base" },
      deviceRun: false,
    });
    const grant = { ...localSupport, llmoptVNext: true as const };
    expect(bind).not.toHaveBeenCalled();
    const device = await prepareConfirmedRun(inputs, squad, false, grant, runId, bind);
    expect(bind).toHaveBeenCalledExactlyOnceWith(device!.inputs.request);
    expect(device?.baseRequest).toMatchObject({
      run: { run_id: runId, stage: "base" },
      deviceRun: true,
      deviceAlternatives: true,
      preferences: { net_points_priority: true },
    });
    expect(await prepareConfirmedRun(inputs, squad, false, grant, undefined, bind)).toBeNull();
    expect(
      await prepareConfirmedRun(
        inputs,
        squad,
        false,
        { ...grant, captureSnapshotId: "old" },
        runId,
        bind,
      ),
    ).toBeNull();
    expect(bind).toHaveBeenCalledTimes(1);
  });
  it("falls back with the same identity when the run's local capacity cannot be retained", async () => {
    const preferred: PlanDraft = { ...draft, soft: [{ kind: "no_hits" }] };
    const selection = {
      ...inputs,
      draft: preferred,
      plans: preparePlans(baseDraft(preferred), held),
    };
    const grant = {
      ...capabilities,
      llmoptVNext: true as const,
      devicePreferenceBundles: true as const,
    };
    const bind = vi.fn(async () => false);
    const run = await prepareConfirmedRun(selection, squad, false, grant, runId, bind);
    expect(bind).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({
        run: { contract_version: "llmopt_run_v1", run_id: runId, stage: "base" },
        deviceRun: true,
      }),
    );
    expect(run?.baseRequest).toMatchObject({
      deviceRun: false,
      run: { run_id: runId, stage: "base" },
    });
    expect(run?.inputs.bundleMode).toBe(false);
    expect(run?.slots.every((slot) => !slot.request || slot.request.deviceRun === false)).toBe(
      true,
    );
    expect(
      (
        await prepareConfirmedRun(
          selection,
          squad,
          false,
          { ...grant, preferenceBundles: true },
          runId,
          undefined,
        )
      )?.inputs.bundleMode,
    ).toBe(true);
    const total = { ...preferred, max_total_cost_tenths: 10 };
    expect(
      await prepareConfirmedRun({ ...selection, draft: total }, squad, false, grant, runId, bind),
    ).toBeNull();
    await expect(
      prepareConfirmedRun(selection, squad, false, grant, runId, async () => {
        throw new Error("RUN_CONTEXT_CHANGED");
      }),
    ).rejects.toThrow("RUN_CONTEXT_CHANGED");
  });
});
