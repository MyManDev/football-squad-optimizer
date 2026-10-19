/**
 * What a switch of prediction model changed (#1131): only a model switch for the same
 * selection is a change; the change names the players the new plan brings in and the net
 * points difference, stays for re-renders, primes its counter at zero, and moves the changed
 * plates once, never under reduced motion.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { forgetCounts, rememberCount } from "../../../design/countMotion";
import { REDUCED_MOTION_QUERY } from "../../../design/motion";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type { AdvicePlayer, EntryAdvice } from "../types";
import {
  forgetShownPlans,
  MODEL_POP,
  modelChangeOf,
  planModel,
  popChanged,
  releasePop,
} from "./modelSwitch";

const BASE = mockEntryAdviceEnvelope(35249001, "saf-puan", 1).payload;

function player(id: number): AdvicePlayer {
  return { player_id: id, name: `P${id}`, short_name: `P${id}`, position: "MID", team: "X" };
}

/** A plan with eleven 1..11 and bench 12..15 unless given, under the given model. */
function plan(
  model: "current" | "football",
  patch: Partial<EntryAdvice> = {},
  ids: number[] = Array.from({ length: 15 }, (_, i) => i + 1),
): EntryAdvice {
  return {
    ...BASE,
    starting_xi: ids.slice(0, 11).map(player),
    bench: ids.slice(11).map(player),
    expected_own_points: 60,
    transfer_hit_points: 0,
    ...(model === "football"
      ? {
          prediction_model: {
            id: "football",
            version: "v1",
            experimental: true,
            fingerprint: "f",
          },
        }
      : { prediction_model: undefined }),
    ...patch,
  };
}

beforeEach(() => {
  forgetShownPlans();
  forgetCounts();
});
afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
});

describe("a model switch", () => {
  it("is not a change on the first plan or on the same plan again", () => {
    expect(modelChangeOf(plan("current"))).toBeNull();
    expect(modelChangeOf(plan("current"))).toBeNull();
    expect(planModel(plan("football"))).toBe("football");
  });

  it("names the players the other model's plan brings in and the net difference", () => {
    modelChangeOf(plan("current"));
    // Players 3 and 14 leave; 30 and 31 come in. 64.5 less a 4-point hit against 60.
    const ids = [1, 2, 30, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 31, 15];
    const change = modelChangeOf(
      plan("football", { expected_own_points: 64.5, transfer_hit_points: 4 }, ids),
    )!;
    expect(change.from).toBe("current");
    expect(change.to).toBe("football");
    expect([...change.changed].sort((a, b) => a - b)).toEqual([30, 31]);
    expect(change.difference).toBeCloseTo(0.5, 9);
  });

  it("stays the same answer while the plan is shown, so the pitch and the decision agree", () => {
    modelChangeOf(plan("current"));
    const first = modelChangeOf(
      plan("football", {}, [16, ...Array.from({ length: 14 }, (_, i) => i + 2)]),
    );
    const again = modelChangeOf(
      plan("football", {}, [16, ...Array.from({ length: 14 }, (_, i) => i + 2)]),
    );
    expect(again).toBe(first);
  });

  it("primes the difference's counter at zero, again on each new switch", () => {
    modelChangeOf(plan("current"));
    const change = modelChangeOf(plan("football", { expected_own_points: 62 }))!;
    expect(rememberCount(change.key, change.difference!)).toBe(0);
    modelChangeOf(plan("current"));
    const back = modelChangeOf(plan("football", { expected_own_points: 62 }))!;
    expect(back.key).toBe(change.key);
    expect(rememberCount(back.key, back.difference!)).toBe(0);
  });

  it.each([
    ["the strategy", { mode: "ortak-koru" as const }],
    ["the window", { window: 3 as const }],
    ["the chip", { chip: "bboost" as const }],
  ])("is not what a switch of %s makes, with the model changed too", (_, patch) => {
    modelChangeOf(plan("current"));
    expect(modelChangeOf(plan("football", patch))).toBeNull();
  });

  it("is not a change when the same model shows a new plan", () => {
    modelChangeOf(plan("current"));
    expect(
      modelChangeOf(
        plan(
          "current",
          {},
          Array.from({ length: 15 }, (_, i) => i + 20),
        ),
      ),
    ).toBeNull();
  });

  it("leaves the difference out where a plan states no points", () => {
    modelChangeOf(plan("current"));
    expect(
      modelChangeOf(plan("football", { expected_own_points: undefined as unknown as number }))!
        .difference,
    ).toBeNull();
  });
});

describe("the changed plates' motion", () => {
  const plate = () => {
    const element = document.createElement("div");
    const animate = vi.fn(
      () => ({ playState: "running", cancel: vi.fn() }) as unknown as Animation,
    );
    Object.defineProperty(element, "animate", { value: animate });
    return { element, animate };
  };

  it("moves each plate once per change, by transform only", () => {
    const a = plate();
    const b = plate();
    expect(popChanged("k", [a.element, b.element])).toHaveLength(2);
    expect(a.animate).toHaveBeenCalledWith(MODEL_POP, expect.objectContaining({ duration: 400 }));
    expect(popChanged("k", [a.element])).toEqual([]);
    for (const frame of MODEL_POP)
      for (const key of Object.keys(frame)) expect(["transform", "offset"]).toContain(key);
    releasePop("k");
    expect(popChanged("k", [a.element])).toHaveLength(1);
  });

  it("does not move under reduced motion", () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: (query: string) => ({ matches: query === REDUCED_MOTION_QUERY }),
    });
    const a = plate();
    expect(popChanged("r", [a.element])).toEqual([]);
    expect(a.animate).not.toHaveBeenCalled();
  });
});
