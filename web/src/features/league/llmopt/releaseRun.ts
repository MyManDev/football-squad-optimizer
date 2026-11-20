import type { AdviceCapabilities } from "../advice/adviceCapabilities";
import { deviceSelection } from "../device/selection";
import type { EntrySquad } from "../types";
import { prepareRun, requestFor, type PlanRun, type RunInputs } from "./planRun";
import { preferenceExecution } from "./preferenceExecution";

/** Prepare the workflow offered by the current server for a freshly confirmed draft. */
export function prepareConfirmedRun(
  inputs: Pick<RunInputs, "draft" | "held" | "plans" | "frozenWeeks" | "reference">,
  squad: EntrySquad,
  forwarded: boolean | undefined,
  capabilities: AdviceCapabilities,
  runId: string | undefined,
): PlanRun | null {
  const { draft, plans, reference } = inputs;
  const heldChips = capabilities.chipsByEntry?.[String(squad.entry.entry_id)];
  const wildcardNotHeld = heldChips !== undefined && !heldChips.includes("wildcard");
  const request = requestFor(squad, forwarded, plans.window);
  if (capabilities.llmoptVNext !== true) {
    if (
      draft.max_total_cost_tenths !== undefined ||
      draft.soft.some((rule) => rule.priority !== undefined)
    )
      return null;
    return prepareRun({
      ...inputs,
      wildcardNotHeld,
      request: { ...request, deviceRun: false, deviceAlternatives: false },
    });
  }
  if (!runId) return null;
  request.run = { contract_version: "llmopt_run_v1", run_id: runId, stage: "base" };
  const localBundle = plans.window === 1 && capabilities.devicePreferenceBundles === true;
  if (draft.max_total_cost_tenths !== undefined && !capabilities.preferenceBundles && !localBundle)
    return null;
  let next = prepareRun({
    ...inputs,
    request,
    wildcardNotHeld,
    compareOnly: reference?.compareOnly === true,
    ...(capabilities.transferPackages && plans.window === 3 ? { paths3w: true as const } : {}),
    bundleMode:
      (capabilities.preferenceBundles === true || localBundle) &&
      draft.soft.length > 0 &&
      !draft.scenario,
  });
  const queries = [
    next.baseRequest,
    ...next.slots.map((slot) => slot.request),
    preferenceExecution(next),
  ];
  if (
    next.inputs.request.deviceRun === true &&
    queries.some((query) => query && deviceSelection(query, squad)?.kind !== "plain")
  )
    next = prepareRun({
      ...next.inputs,
      request: { ...next.inputs.request, deviceRun: false, deviceAlternatives: false },
    });
  if (
    next.inputs.bundleMode &&
    next.baseRequest?.deviceRun === false &&
    !capabilities.preferenceBundles
  ) {
    if (draft.max_total_cost_tenths !== undefined) return null;
    next = prepareRun({ ...next.inputs, bundleMode: false });
  }
  return next;
}
