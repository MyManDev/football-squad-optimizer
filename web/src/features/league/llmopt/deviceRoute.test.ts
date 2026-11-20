import { describe, expect, it } from "vitest";
import fixture from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import type { DevicePlanEntry } from "../device/types";
import { preparePlans, type PlanDraft } from "./intent";
import { baseDraft, prepareRun, requestFor, restoreRun } from "./planRun";
import { prepareCombined } from "./combinedPlan";

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
