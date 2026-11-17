import { describe, expect, it } from "vitest";

import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import type { AdviceRequest } from "../advice/adviceClient";
import { preparePlans, type Constraint, type PlanDraft } from "./intent";
import { baseDraft, prepareRun, requestFor, restoreRun } from "./planRun";

const squad = mockEntrySquadEnvelopes[35249001]!.payload;
const held = new Set([...squad.starting_xi, ...squad.bench].map(({ player_id }) => player_id));
const heldId = squad.starting_xi[0]!.player_id;
const include = (player_id: number, max_cost_tenths?: number): Constraint => ({
  kind: "include_player",
  player_id,
  ...(max_cost_tenths === undefined ? {} : { max_cost_tenths }),
});

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

describe("prepareRun", () => {
  it("sends only the required-rule plan when nothing is preferred", () => {
    const prepared = run({ hard: [{ kind: "no_hits" }], soft: [] });
    expect(prepared.baseTitle).toBe("base");
    expect(prepared.baseRequest?.preferences).toMatchObject({ no_hits: true });
    expect(prepared.baseRequest?.preferences).not.toHaveProperty("net_points_priority");
    expect(prepared.slots).toEqual([]);
    expect(prepared.prices).toEqual([]);
    expect(prepared.automaticBasis).toBe(prepared.baseRequest);
  });

  it("prices one preferred rule in the first slot against the required-rule plan", () => {
    const prepared = run({ hard: [{ kind: "no_hits" }], soft: [include(901, 15)] });
    expect(prepared.baseRequest?.preferences).toMatchObject({
      no_hits: true,
      net_points_priority: true,
    });
    expect(prepared.baseRequest?.preferences).not.toHaveProperty("include_players");
    expect(prepared.slots).toHaveLength(1);
    expect(prepared.slots[0]).toMatchObject({
      kind: "priced",
      request: { preferences: { include_players: [901], net_points_priority: true } },
    });
    expect(prepared.prices.map(({ outcome }) => outcome)).toEqual([0]);
  });

  it("gives two preferred rules a slot each", () => {
    const prepared = run({ hard: [], soft: [include(901), include(902)] });
    expect(prepared.slots.map((slot) => slot.request?.preferences.include_players)).toEqual([
      [901],
      [902],
    ]);
    expect(prepared.prices.map(({ outcome }) => outcome)).toEqual([0, 1]);
  });

  it("marks a third preferred rule as having no slot of its own", () => {
    const prepared = run({ hard: [], soft: [include(901), include(902), include(903)] });
    expect(prepared.slots).toHaveLength(2);
    expect(prepared.prices.map(({ outcome }) => outcome)).toEqual([0, 1, "skipped"]);
  });

  it("shares a slot between rules that ask for the same plan", () => {
    const prepared = run({
      hard: [],
      soft: [include(901), { ...include(901), max_cost_tenths: 5 }],
    });
    expect(prepared.slots).toHaveLength(1);
    expect(prepared.prices.map(({ outcome }) => outcome)).toEqual([0, 0]);
  });

  it("names a rule that changes nothing, one that conflicts and one that needs a missing chip", () => {
    const prepared = run(
      {
        hard: [{ kind: "keep_player", player_id: heldId }],
        soft: [
          { kind: "keep_player", player_id: heldId },
          { kind: "avoid_player", player_id: heldId },
          { kind: "wildcard" },
        ],
      },
      true,
    );
    expect(prepared.prices.map(({ outcome }) => outcome)).toEqual([
      "same",
      "conflict",
      "unavailable",
    ]);
    expect(prepared.slots).toEqual([]);
    expect(prepared.wildcardUnavailable).toBe(true);
  });

  it("does not price preferred rules while a with-and-without comparison holds both slots", () => {
    const prepared = run({
      hard: [],
      soft: [include(901)],
      comparison: { ...include(902), both: true },
    });
    expect(prepared.slots.map((slot) => slot.kind === "explicit" && slot.title)).toEqual([
      "without",
      "with",
    ]);
    expect(prepared.prices.map(({ outcome }) => outcome)).toEqual(["skipped"]);
  });
});

describe("restoreRun", () => {
  const draft: PlanDraft = { hard: [{ kind: "no_hits" }], soft: [include(901)] };
  const window = (value: AdviceRequest["window"]) => requestFor(squad, false, value);

  it("rebuilds the run a saved confirmation stands for", () => {
    const restored = restoreRun({ draft, confirmation: { wildcardNotHeld: false } }, held, window);
    const { baseRequest, slots, prices } = run(draft);
    expect(restored).toMatchObject({ baseRequest, slots, prices, inputs: { draft, held } });
  });

  it("restores nothing without a confirmation or once the required rules conflict", () => {
    expect(restoreRun({ draft }, held, window)).toBeNull();
    expect(restoreRun(null, held, window)).toBeNull();
    const conflict: PlanDraft = {
      hard: [
        { kind: "keep_player", player_id: heldId },
        { kind: "avoid_player", player_id: heldId },
      ],
      soft: [],
    };
    expect(
      restoreRun({ draft: conflict, confirmation: { wildcardNotHeld: false } }, held, window),
    ).toBeNull();
  });
});
