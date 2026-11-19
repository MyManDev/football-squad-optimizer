/** Invoke the current web orchestration, rather than copying its slot accounting. */
import { readFileSync } from "node:fs";
import { preparePlans } from "../../../web/src/features/league/llmopt/intent";
import { prepareRun } from "../../../web/src/features/league/llmopt/planRun";
import { combinedCandidates, prepareCombined } from "../../../web/src/features/league/llmopt/combinedPlan";

const input = JSON.parse(readFileSync(0, "utf8"));
const held = new Set<number>(input.held);
const draft = input.draft;
const plans = preparePlans({ ...draft, soft: [] }, held);
const run = prepareRun({ draft, held, request: input.request, plans, wildcardNotHeld: false });
let combined = null;
if (input.results) {
  const review = run.prices.map((target) => ({
    outcome: target.outcome,
    price: {
      status: typeof target.outcome === "number"
        ? (input.results[target.outcome]?.has_solution ? "priced" : "unavailable")
        : target.outcome === "same" ? "priced" : target.outcome,
      aboveCeiling: false,
    },
  }));
  const candidates = combinedCandidates(run, review as never);
  if (candidates) combined = prepareCombined(run, candidates);
}
process.stdout.write(JSON.stringify({ base: run.baseRequest, slots: run.slots, prices: run.prices, combined }));
