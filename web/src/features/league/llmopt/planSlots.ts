import { useMemo } from "react";

import type { AdviceClient } from "../advice/adviceClient";
import { checkedPreferences, holdsOpeningTransfers } from "../advice/decisionPreferences";
import {
  sameAdviceRequest,
  useAdviceJob,
  type AdviceJob,
  type ComputePhase,
} from "../advice/useAdviceJob";
import type { EntryAdvice } from "../types";
import { delayedBuyPreferences } from "./planPaths";
import { openingAlternatives } from "./planComparison";
import type { PlanRequest, PlanRun } from "./planRun";
import type { ALTERNATIVE_COUNT, StartedAlternative } from "./planSession";

/** The run's alternative slots, in the order the run reserves them. */
export const ALTERNATIVE_SLOTS = ["first", "second"] as const satisfies readonly string[] & {
  length: typeof ALTERNATIVE_COUNT;
};
export type AlternativeSlot = (typeof ALTERNATIVE_SLOTS)[number];
/** The base plan, the alternatives, and the plan with all accepted preferences. */
export type SlotName = "base" | AlternativeSlot | "combined";

/** A job's actions. Each is stable across renders, so effects can depend on them. */
export type JobControls = Pick<AdviceJob, "compute" | "resume" | "readCached" | "reset">;

export interface PlanJobs {
  states: Record<SlotName, ComputePhase>;
  controls: Record<SlotName, JobControls>;
}

export function isWorking(phase: ComputePhase["phase"]) {
  return phase === "requesting" || phase === "waiting";
}

function useControls({ compute, resume, readCached, reset }: AdviceJob): JobControls {
  return useMemo(
    () => ({ compute, resume, readCached, reset }),
    [compute, resume, readCached, reset],
  );
}

/**
 * One advice job per named slot, mounted in a fixed order: base, the alternatives, then the
 * plan with all preferences.
 */
export function usePlanJobs(client: AdviceClient, snapshotId: string | null | undefined): PlanJobs {
  const base = useAdviceJob(client, false, snapshotId, true);
  const first = useAdviceJob(client, false, snapshotId, true);
  const second = useAdviceJob(client, false, snapshotId, true);
  const combined = useAdviceJob(client, false, snapshotId, true);
  const baseControls = useControls(base);
  const firstControls = useControls(first);
  const secondControls = useControls(second);
  const combinedControls = useControls(combined);
  const controls = useMemo(
    () => ({
      base: baseControls,
      first: firstControls,
      second: secondControls,
      combined: combinedControls,
    }),
    [baseControls, firstControls, secondControls, combinedControls],
  );
  return {
    states: {
      base: base.state,
      first: first.state,
      second: second.state,
      combined: combined.state,
    },
    controls,
  };
}

/** The states of the alternative slots, in slot order. */
export function alternativeStates(jobs: PlanJobs): ComputePhase[] {
  return ALTERNATIVE_SLOTS.map((slot) => jobs.states[slot]);
}

/** A request started once the base plan is in, and how a reload finds it again. */
export interface Followup {
  request: PlanRequest;
  alternative: StartedAlternative;
}

/**
 * What each alternative slot starts once the base plan is in: the priced rules' plans, or, when
 * nothing is priced and a slot is free, a plan that rolls the transfer or keeps more budget.
 */
export function followupRequests(run: PlanRun, basePlan: EntryAdvice): (Followup | null)[] {
  if (basePlan.device_alternatives || run.inputs.request.deviceAlternatives) return [];
  const basis = run.automaticBasis;
  if (!basis) return [];
  const followups = run.slots.map((slot): Followup | null =>
    slot.kind === "priced" ? { request: slot.request, alternative: { kind: "priced" } } : null,
  );
  if (run.prices.length || run.slots.length >= ALTERNATIVE_SLOTS.length) return followups;
  const reserved = run.slots.flatMap((slot) => (slot.request ? [slot.request] : []));
  const { roll, bank } = openingAlternatives(basePlan, basis.preferences, basis.chip);
  const bankFloor = bank?.min_opening_bank_tenths;
  const available: Followup[] = [];
  if (roll && !reserved.some(({ preferences }) => holdsOpeningTransfers(preferences))) {
    const players =
      basePlan.plan_weeks
        ?.find((week) => week.gameweek === basePlan.gameweek)
        ?.transfers_in.map((p) => p.player_id) ?? [];
    const delayed = run.inputs.paths3w ? delayedBuyPreferences(roll, players) : null;
    available.push({
      request: { ...basis, preferences: delayed ?? roll },
      alternative: delayed ? { kind: "delay", players } : { kind: "roll" },
    });
  }
  if (bank && bankFloor !== undefined)
    available.push({
      request: { ...basis, preferences: bank },
      alternative: { kind: "bank", floor: bankFloor },
    });
  return [
    ...followups,
    ...available
      .filter(({ request }) => !reserved.some((other) => sameAdviceRequest(request, other)))
      .slice(0, ALTERNATIVE_SLOTS.length - run.slots.length),
  ];
}

/**
 * The request a reload restores in an alternative slot, or null when that slot had none.
 *
 * Requested branches are known from the draft. A priced rule's slot, and an automatic roll or
 * bank alternative, are restored only when the saved run records that it was started.
 */
export function restoredSlot(
  run: PlanRun,
  index: number,
  started?: StartedAlternative | null,
): PlanRequest | null {
  const slot = run.slots[index];
  if (slot?.kind === "explicit") return slot.request;
  if (slot?.kind === "priced") return started?.kind === "priced" ? slot.request : null;
  const basis = run.automaticBasis;
  if (!basis || run.prices.length || !started || started.kind === "priced") return null;
  try {
    if (started.kind === "delay") {
      if (!run.inputs.paths3w) return null;
      const preferences = delayedBuyPreferences(basis.preferences, started.players);
      return preferences ? { ...basis, preferences } : null;
    }
    return {
      ...basis,
      preferences: checkedPreferences({
        ...basis.preferences,
        ...(started.kind === "bank"
          ? { min_opening_bank_tenths: started.floor }
          : { hold_opening_transfers: true }),
      }),
    };
  } catch {
    return null;
  }
}
