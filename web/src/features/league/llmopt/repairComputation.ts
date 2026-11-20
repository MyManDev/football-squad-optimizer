import { cancellableDelay, withRequestDeadline } from "../../../data/request";
import {
  adviceRequestBody,
  type AdviceClient,
  type AdviceRequest,
  type RepairRuleFragment,
} from "../advice/adviceClient";
import { checkedAdvice } from "../advice/adviceResponse";
import { checkedPreferences } from "../advice/decisionPreferences";
import { PATIENCE_EXHAUSTED, PATIENCE_MS, QUEUE_PATIENCE_MS } from "../advice/useAdviceJob";
import type { EntryAdvice, EntrySquad } from "../types";
import { type Constraint, type PlanDraft, preparePlans, ruleFields } from "./intent";
import { expectedNet, hasPlanLineup, plannedWeeks } from "./planComparison";
import { planContent, planData } from "./planHistory";
import { freezeReference, summarizeRevision, type PlanRevision } from "./planRevision";
import { baseDraft, prepareRun, requestFor, type PlanRequest } from "./planRun";
import { frozenForDraft } from "./planScenario";
import { preferenceExecution } from "./preferenceExecution";

export interface RepairRun {
  runId: string;
  dataId: string;
  failedBase: boolean;
  sourceDraft?: PlanDraft;
}

function serverRepairEnvelope(request: PlanRequest): PlanRequest {
  // Match the API's four-KiB POST gate, including UTF-8 club names and current lineup pins.
  if (
    request.window === 3 &&
    new TextEncoder().encode(adviceRequestBody(request)).byteLength > 4096
  )
    throw new Error("RUN_REPAIR_INVALID");
  return request;
}

/** An unresolved original can contain two rules that a single job could never serialize. */
function originalRules(draft: PlanDraft, reference?: PlanRevision) {
  const rules: Constraint[] = [...draft.hard];
  if (
    !draft.scenario &&
    !draft.soft.length &&
    draft.comparison?.kind === "include_player" &&
    draft.comparison.both
  ) {
    rules.push({
      kind: "avoid_player",
      player_id: draft.comparison.player_id,
      week: draft.comparison.week,
    });
  }
  const frozen = frozenForDraft({ ...draft, window: 3 }, reference);
  const wildcards = new Set(
    rules.flatMap((rule) => (rule.kind === "wildcard" ? [rule.week ?? 1] : [])),
  );
  const fragments: RepairRuleFragment[] = [];
  for (const rule of rules) {
    if (rule.kind === "wildcard" || rule.kind === "hit_budget") continue;
    const fields = Object.fromEntries(
      Object.entries(ruleFields([rule])).filter(([, value]) =>
        Array.isArray(value) ? value.length > 0 : value === true,
      ),
    );
    fragments.push(rule.week ? { week_rules: [{ week: rule.week, rules: fields }] } : fields);
  }
  const hitCaps = rules.flatMap((rule) => (rule.kind === "hit_budget" ? [rule.points] : []));
  if (!wildcards.size && !frozen.some((week) => week.chip === "wildcard"))
    fragments.push({ save_chips: true });
  if (hitCaps.length) fragments.push({ max_hit_points: Math.min(...hitCaps) });
  if (draft.min_bank) fragments.push({ min_bank: draft.min_bank });
  if (draft.scenario) fragments.push({ scenario: draft.scenario });
  if (draft.soft.length || draft.scenario || reference?.compareOnly)
    fragments.push({ net_points_priority: true });
  for (const week of frozen) fragments.push({ frozen_weeks: [week] });
  return { preferences: fragments, wildcard_weeks: [...wildcards].sort() };
}

export function candidateRequest(
  draft: PlanDraft,
  basis: { squad: EntrySquad; window: 1 | 3; forwarded?: boolean; reference?: PlanRevision },
  run: RepairRun,
  stage: "base" | "repair",
): PlanRequest | null {
  const { squad, window, forwarded, reference } = basis;
  const held = new Set([...squad.starting_xi, ...squad.bench].map((p) => p.player_id));
  const fixedWindow = { ...draft, window };
  const frozenWeeks = frozenForDraft(fixedWindow, reference);
  const plans = preparePlans(baseDraft(fixedWindow), held, frozenWeeks);
  if (plans.hardConflict) return null;
  if (
    draft.soft.some((rule) => rule.priority !== undefined) &&
    draft.max_total_cost_tenths === undefined
  )
    return null;
  if (
    draft.max_total_cost_tenths !== undefined &&
    draft.soft.some((rule) => rule.kind === "wildcard")
  )
    return null;
  const prepared = prepareRun({
    draft: fixedWindow,
    plans,
    held,
    frozenWeeks,
    reference,
    compareOnly: reference?.compareOnly === true,
    bundleMode: draft.soft.length > 0,
    wildcardNotHeld: false,
    request: requestFor(squad, forwarded, window, window === 1),
  });
  let request = prepared.baseRequest;
  if (request && draft.soft.length) {
    if (window === 1) request = preferenceExecution(prepared);
    else if (
      draft.max_total_cost_tenths !== undefined ||
      prepared.prices.some(({ outcome }) => outcome !== "same" && outcome !== "conflict")
    ) {
      // Changed three-week rules need their own main (122), preference execution
      // (366), and replay (122). All three cannot fit the run's 488-unit ceiling.
      throw new Error("RUN_BUDGET_EXHAUSTED");
    }
  }
  // Keep the prepared objective and rules. A repair displays one witness for the edited draft.
  return (
    request &&
    serverRepairEnvelope({
      ...request,
      run: {
        contract_version: "llmopt_run_v1",
        run_id: run.runId,
        stage,
        ...(window === 3 && !run.failedBase && run.sourceDraft
          ? { repair_origin: originalRules(run.sourceDraft, reference) }
          : {}),
      },
      ...(window === 1
        ? { deviceRun: true, deviceAlternatives: false, deviceRepair: { dataId: run.dataId } }
        : { deviceRun: false }),
    })
  );
}

function preferredWitness(parent: EntryAdvice) {
  const result = parent.preference_bundle_result;
  if (!result) return parent;
  if (result.budget_exhausted) throw new Error("RUN_BUDGET_EXHAUSTED");
  for (const [index, component] of result.components.entries()) {
    if (
      result.request.slots[index] &&
      component.status !== "done" &&
      component.error_code !== "PLAN_NOT_FOUND"
    )
      throw new Error(component.error_code ?? "INPUTS_UNAVAILABLE");
  }
  if (result.selected) {
    if (result.selected.status === "done" && result.selected.payload)
      return result.selected.payload;
    throw new Error(result.selected.error_code ?? "INPUTS_UNAVAILABLE");
  }
  if (
    result.request.program ||
    result.request.choices.find(({ accepted }) => accepted === result.accepted)?.selection
  )
    throw new Error("INPUTS_UNAVAILABLE");
  // A single accepted price uses its existing component; the ordinary price
  // execution only creates a combined selection when multiple choices need one.
  const slots = new Set(
    result.request.prices.flatMap(({ outcome }, index) =>
      typeof outcome === "number" && (result.accepted & (1 << index)) !== 0 ? [outcome] : [],
    ),
  );
  if (!slots.size) return parent;
  const [slot] = slots;
  const component = result.components[slot!];
  if (slots.size !== 1 || component?.status !== "done" || !component.payload)
    throw new Error("INPUTS_UNAVAILABLE");
  return component.payload;
}

export function verificationRequest(
  request: PlanRequest,
  witness: EntryAdvice,
): PlanRequest | null {
  if (!request.run) return null;
  const run = { ...request.run, stage: "repair" as const };
  if (request.window === 1)
    return request.deviceRepair
      ? {
          ...request,
          run,
          deviceAlternatives: false,
          deviceRepair: { ...request.deviceRepair, verify: true },
        }
      : null;
  const revision = summarizeRevision(witness);
  const pins = freezeReference(revision, [1, 2, 3]);
  if (pins.length !== 3 || pins.some((week) => week.starting_xi?.length !== 11 || !week.captain))
    return null;
  return serverRepairEnvelope({
    ...request,
    run,
    preferences: checkedPreferences({ ...request.preferences, frozen_weeks: pins }),
  });
}

/** POST on the same run even for a cache hit, so the server can bind the witness to this run. */
export async function computeRepairPlan(
  client: AdviceClient,
  request: AdviceRequest,
  snapshotId: string,
  dataId: string,
  signal: AbortSignal,
) {
  const outcome = await withRequestDeadline((signal) => client.requestAdvice(request, { signal }), {
    signal,
    timeoutMs: client.localRequestAllowanceMs?.(request),
  });
  if (outcome.kind === "unavailable") throw new Error(outcome.reason ?? "INPUTS_UNAVAILABLE");
  let answer;
  if (outcome.kind === "job") {
    const started = Date.now();
    let running = outcome.status === "running";
    let deadline = started + (running ? PATIENCE_MS[request.window] : QUEUE_PATIENCE_MS);
    for (;;) {
      signal.throwIfAborted();
      if (Date.now() >= deadline) throw new Error(PATIENCE_EXHAUSTED);
      const job = await withRequestDeadline((signal) => client.readJob(outcome.jobId, { signal }), {
        signal,
      });
      if (job.status === "completed") break;
      if (job.status === "failed" || job.status === "cancelled")
        throw new Error(job.errorCode ?? "ADVICE_FAILED");
      if (!running && job.status === "running") {
        running = true;
        deadline = Date.now() + PATIENCE_MS[request.window];
      }
      const interval = Date.now() - started < 60000 ? 2000 : 5000;
      await cancellableDelay(Math.min(interval, Math.max(0, deadline - Date.now())), signal);
    }
    answer = await withRequestDeadline(
      (signal) => client.readAdvice(request, { signal, publishedFallback: false }),
      { signal },
    );
  } else answer = outcome;
  if (answer.kind !== "advice" || answer.source !== (request.window === 1 ? "device" : "api-cache"))
    throw new Error("INPUTS_UNAVAILABLE");
  const envelope = checkedAdvice(answer.envelope, request);
  const payload = request.preferenceBundle ? preferredWitness(envelope.payload) : envelope.payload;
  if (payload.wall_clock_stopped_the_search === true) throw new Error("RUN_BUDGET_EXHAUSTED");
  const weeks = plannedWeeks(payload);
  if (
    payload.data_quality === "empty" ||
    (payload.solver_status !== "OPTIMAL" && payload.solver_status !== "FEASIBLE") ||
    !hasPlanLineup(payload) ||
    !weeks?.every((week) => hasPlanLineup(week.lineup)) ||
    expectedNet(payload) === null
  )
    throw new Error("INPUTS_UNAVAILABLE");
  const provenance = planData(payload);
  if (
    payload.source_snapshot_id !== snapshotId ||
    provenance?.id !== dataId ||
    provenance.kind !== (request.window === 1 ? "device" : "server")
  )
    throw new Error("RUN_CONTEXT_CHANGED");
  return payload;
}

export function matchesRepair(witness: EntryAdvice, result: EntryAdvice) {
  return (
    expectedNet(result) === expectedNet(witness) && planContent(result) === planContent(witness)
  );
}
