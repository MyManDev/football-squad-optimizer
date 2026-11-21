import {
  capabilitiesForPage,
  llmoptEnabledForWindow,
  type AdviceCapabilities,
} from "../advice/adviceCapabilities";
import type { AdviceClient } from "../advice/adviceClient";
import { deviceSelection } from "../device/selection";
import type { EntrySquad } from "../types";
import { prepareRun, requestFor, type PlanRun, type RunInputs } from "./planRun";
import { preferenceExecution } from "./preferenceExecution";

export function confirmationProblem(
  draft: RunInputs["draft"],
  window: RunInputs["plans"]["window"],
  capabilities: AdviceCapabilities,
) {
  const hasPriority = draft.soft.some(({ priority }) => priority !== undefined);
  const hasTotal = draft.max_total_cost_tenths !== undefined;
  const grouped =
    llmoptEnabledForWindow(capabilities, window) &&
    (capabilities.preferenceBundles === true ||
      (window === 1 && capabilities.devicePreferenceBundles === true));
  if (!grouped && (hasPriority || hasTotal)) return "individualLimitsOnly";
  if (hasPriority && !hasTotal) return "totalRequired";
  if (
    hasTotal &&
    (draft.scenario || !draft.soft.length || draft.soft.some(({ kind }) => kind === "wildcard"))
  )
    return "totalUnavailable";
  return null;
}

/** Prepare the workflow offered by the current server for a freshly confirmed draft. */
export async function prepareConfirmedRun(
  inputs: Pick<RunInputs, "draft" | "held" | "plans" | "frozenWeeks" | "reference">,
  squad: EntrySquad,
  forwarded: boolean | undefined,
  capabilities: AdviceCapabilities,
  runId: string | undefined,
  prepareDeviceRun: AdviceClient["prepareDeviceRun"],
): Promise<PlanRun | null> {
  const { draft, plans, reference } = inputs;
  if (
    !capabilitiesForPage(capabilities, {
      leagueId: squad.league_id,
      season: squad.season,
      gameweek: squad.gameweek,
      snapshotId: squad.source_snapshot_id,
    }) ||
    !capabilities.preferences ||
    !capabilities.strategies["saf-puan"]?.windows.includes(plans.window)
  )
    return null;
  if (confirmationProblem(draft, plans.window, capabilities)) return null;
  // Public entries may have no chip history until their inputs are pinned.
  const heldChips = capabilities.chipsByEntry?.[String(squad.entry.entry_id)];
  const wildcardNotHeld = heldChips !== undefined && !heldChips.includes("wildcard");
  const enabled = llmoptEnabledForWindow(capabilities, plans.window);
  const localBundle =
    enabled && plans.window === 1 && capabilities.devicePreferenceBundles === true;
  const request = requestFor(squad, forwarded, plans.window, localBundle);
  if (!enabled) return prepareRun({ ...inputs, wildcardNotHeld, request });
  if (!runId) return null;
  request.run = { contract_version: "llmopt_run_v1", run_id: runId, stage: "base" };
  let next = prepareRun({
    ...inputs,
    request,
    wildcardNotHeld,
    compareOnly: reference?.compareOnly === true,
    ...(capabilities.threeWeekPaths === true && plans.window === 3
      ? { paths3w: true as const }
      : {}),
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
    (queries.some((query) => query && deviceSelection(query, squad)?.kind !== "plain") ||
      !(await prepareDeviceRun?.(next.inputs.request)))
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
