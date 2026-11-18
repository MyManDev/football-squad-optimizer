import { describe, expect, it } from "vitest";

import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { combinedCandidates, prepareCombined } from "./combinedPlan";
import { preparePlans, type Constraint, type PlanDraft } from "./intent";
import type { PreferencePrice } from "./PlanResult";
import type { PriceReview } from "./planResults";
import { baseDraft, prepareRun, requestFor } from "./planRun";

const squad = mockEntrySquadEnvelopes[35249001]!.payload;
const held = new Set([...squad.starting_xi, ...squad.bench].map(({ player_id }) => player_id));
const include = (player_id: number): Constraint => ({ kind: "include_player", player_id });

function run(draft: PlanDraft, wildcardNotHeld = false) {
  const plans = preparePlans(baseDraft(draft), held);
  return prepareRun({
    draft,
    held,
    request: requestFor(squad, false, plans.window),
    plans,
    wildcardNotHeld,
  });
}

type Status = "accepted" | "above" | "pending" | "unavailable" | "conflict" | "skipped";

/** The price review the page shows for a run, one status per preferred rule. */
function review(prepared: ReturnType<typeof run>, statuses: Status[]): PriceReview[] {
  return prepared.prices.map(({ outcome }, index): PriceReview => {
    const status = statuses[index]!;
    const base = { key: String(index), label: String(index) };
    const price: PreferencePrice =
      status === "accepted" || status === "above"
        ? { ...base, status: "priced", cost: 1, aboveCeiling: status === "above" }
        : { ...base, status };
    return { outcome, price };
  });
}

describe("combinedCandidates", () => {
  it("is not due for one preferred rule", () => {
    const one = run({ hard: [], soft: [include(901)] });
    expect(combinedCandidates(one, review(one, ["accepted"]))).toBeNull();
  });

  it("is due once two preferred rules are each accepted", () => {
    const two = run({ hard: [], soft: [include(901), include(902)] });
    expect(combinedCandidates(two, review(two, ["accepted", "accepted"]))).toEqual([0, 1]);
  });

  it("is not due while a rule is above its limit or its price is not in", () => {
    const two = run({ hard: [], soft: [include(901), include(902)] });
    expect(combinedCandidates(two, review(two, ["accepted", "above"]))).toBeNull();
    expect(combinedCandidates(two, review(two, ["accepted", "unavailable"]))).toBeNull();
    expect(combinedCandidates(two, review(two, ["accepted", "pending"]))).toBeNull();
  });

  it("is not due when two accepted rules priced the same plan", () => {
    const shared = run({ hard: [], soft: [include(901), { ...include(901), max_cost_tenths: 9 }] });
    expect(combinedCandidates(shared, review(shared, ["accepted", "accepted"]))).toBeNull();
  });

  it("takes a third rule with no slot of its own beside the accepted ones", () => {
    const three = run({ hard: [], soft: [include(901), include(902), include(903)] });
    expect(three.prices.map(({ outcome }) => outcome)).toEqual([0, 1, "skipped"]);
    expect(combinedCandidates(three, review(three, ["accepted", "accepted", "skipped"]))).toEqual([
      0, 1, 2,
    ]);
    expect(combinedCandidates(three, review(three, ["above", "accepted", "skipped"]))).toEqual([
      1, 2,
    ]);
    expect(combinedCandidates(three, review(three, ["above", "above", "skipped"]))).toEqual([2]);
  });

  it("requires a bounded rule's own price before adding it to a combined plan", () => {
    const bounded = run({
      hard: [],
      soft: [include(901), include(902), { ...include(903), max_cost_tenths: 0 }],
    });
    expect(bounded.prices.map(({ outcome }) => outcome)).toEqual([0, 1, "skipped"]);
    expect(
      combinedCandidates(bounded, review(bounded, ["accepted", "accepted", "skipped"])),
    ).toEqual([0, 1]);
    expect(combinedCandidates(bounded, review(bounded, ["above", "above", "skipped"]))).toBeNull();
  });

  it("leaves a conflicting rule out of the candidates", () => {
    const heldId = squad.starting_xi[0]!.player_id;
    const mixed = run({
      hard: [{ kind: "keep_player", player_id: heldId }],
      soft: [include(901), { kind: "avoid_player", player_id: heldId }, include(902)],
    });
    expect(combinedCandidates(mixed, review(mixed, ["accepted", "conflict", "accepted"]))).toEqual([
      0, 2,
    ]);
  });

  it("is never due for a scenario or a run without preferred rules", () => {
    const plain = run({ hard: [{ kind: "no_hits" }], soft: [] });
    expect(combinedCandidates(plain, [])).toBeNull();
  });
});

describe("prepareCombined", () => {
  it("applies every candidate beside the required rules", () => {
    const three = run({
      hard: [{ kind: "no_hits" }],
      soft: [include(901), include(902), include(903)],
    });
    const combined = prepareCombined(three, [0, 1, 2]);
    expect(combined.applied).toEqual([0, 1, 2]);
    expect(combined.request?.preferences).toMatchObject({
      no_hits: true,
      net_points_priority: true,
      include_players: [901, 902, 903],
    });
    expect(combined.request).toMatchObject({ entryId: squad.entry.entry_id, window: 1 });
  });

  it("leaves out a rule that cannot be added to those already applied, and names the rest", () => {
    const clash = run({
      hard: [],
      soft: [include(901), { kind: "avoid_player", player_id: 901 }, include(902)],
    });
    const combined = prepareCombined(clash, [0, 1, 2]);
    expect(combined.applied).toEqual([0, 2]);
    expect(combined.request?.preferences).toMatchObject({ include_players: [901, 902] });
    expect(combined.request?.preferences.avoid_players ?? []).toEqual([]);
  });

  it("leaves out a Wildcard the team does not hold", () => {
    const wildcard = run(
      { hard: [], soft: [include(901), { kind: "wildcard" }, include(902)] },
      true,
    );
    const combined = prepareCombined(wildcard, [0, 1, 2]);
    expect(combined.applied).toEqual([0, 2]);
    expect(combined.request?.chip).toBeNull();
  });

  it("applies nothing when no candidate fits", () => {
    const heldId = squad.starting_xi[0]!.player_id;
    const blocked = run({
      hard: [{ kind: "keep_player", player_id: heldId }],
      soft: [{ kind: "avoid_player", player_id: heldId }],
    });
    expect(prepareCombined(blocked, [0])).toEqual({ applied: [], request: null });
  });

  it("rebuilds the same request from the rules a saved run applied", () => {
    const three = run({ hard: [], soft: [include(901), include(902), include(903)] });
    const first = prepareCombined(three, [0, 1, 2]);
    expect(prepareCombined(three, first.applied)).toEqual(first);
  });

  it("filters an unpriced bounded rule from a previously saved combined selection", () => {
    const bounded = run({
      hard: [],
      soft: [
        { ...include(901), max_cost_tenths: 15 },
        include(902),
        { ...include(903), max_cost_tenths: 0 },
      ],
    });
    const combined = prepareCombined(bounded, [0, 1, 2]);
    expect(combined.applied).toEqual([0, 1]);
    expect(combined.request?.preferences.include_players).toEqual([901, 902]);
    expect(prepareCombined(bounded, [2])).toEqual({ applied: [], request: null });
  });
});
