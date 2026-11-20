import { describe, expect, it } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { preparePlans, type PlanDraft } from "./intent";
import { visibleAutomatic } from "./planResults";
import { baseDraft, prepareRun, requestFor } from "./planRun";
import { ALTERNATIVE_SLOTS, followupRequests, restoredSlot } from "./planSlots";
import { ALTERNATIVE_COUNT } from "./planSession";

const squad = mockEntrySquadEnvelopes[35249001]!.payload;
const held = new Set([...squad.starting_xi, ...squad.bench].map(({ player_id }) => player_id));

function run(draft: PlanDraft) {
  const plans = preparePlans(baseDraft(draft), held);
  return prepareRun({
    draft,
    held,
    request: requestFor(squad, false, plans.window),
    plans,
    wildcardNotHeld: false,
  });
}

it("names one alternative slot per reserved position", () => {
  expect(ALTERNATIVE_SLOTS).toHaveLength(ALTERNATIVE_COUNT);
});

describe("restoredSlot", () => {
  it("restores a requested branch from the draft alone", () => {
    const compared = run({
      hard: [],
      soft: [],
      comparison: { kind: "include_player", player_id: 901 },
    });
    expect(restoredSlot(compared, 0)).toBe(compared.slots[0]?.request);
  });

  it("restores a priced plan only when the saved run started it", () => {
    const priced = run({ hard: [], soft: [{ kind: "include_player", player_id: 901 }] });
    expect(restoredSlot(priced, 0, { kind: "priced" })).toBe(priced.slots[0]?.request);
    expect(restoredSlot(priced, 0)).toBeNull();
    expect(restoredSlot(priced, 0, { kind: "roll" })).toBeNull();
    expect(restoredSlot(priced, 1, { kind: "roll" })).toBeNull();
  });

  it("rebuilds a started roll or bank alternative from the base request", () => {
    const plain = run({ hard: [{ kind: "no_hits" }], soft: [] });
    expect(restoredSlot(plain, 0, { kind: "roll" })?.preferences).toMatchObject({
      no_hits: true,
      hold_opening_transfers: true,
    });
    expect(restoredSlot(plain, 1, { kind: "bank", floor: 25 })?.preferences).toMatchObject({
      no_hits: true,
      min_opening_bank_tenths: 25,
    });
    expect(restoredSlot(plain, 0)).toBeNull();
    expect(restoredSlot(plain, 0, null)).toBeNull();
  });
});

describe("followupRequests", () => {
  const plan = mockEntryAdviceEnvelope(35249001, "saf-puan", 1).payload;

  it.each(["hold", "frozen"] as const)(
    "keeps the ordinary roll and restores it when a week-two %s blocks the delayed buy",
    (condition) => {
      const draft: PlanDraft = {
        window: 3,
        hard: condition === "hold" ? [{ kind: "hold_transfers", week: 2 }] : [],
        soft: [],
        ...(condition === "frozen" ? { keep_weeks: [2] } : {}),
      };
      const frozenWeeks =
        condition === "frozen"
          ? [{ week: 2 as const, transfers_in: [], transfers_out: [], chip: null }]
          : [];
      const inputs = {
        draft,
        held,
        frozenWeeks,
        request: requestFor(squad, false, 3),
        plans: preparePlans(baseDraft(draft), held, frozenWeeks),
        wildcardNotHeld: false,
      };
      const envelope = mockEntryAdviceEnvelope(35249001, "saf-puan", 3);
      const main = envelope.payload;
      main.bank_after_tenths = 20;
      main.plan_weeks![0]!.free_transfers_after = 1;
      const plain = followupRequests(prepareRun(inputs), main);
      const enabled = prepareRun({ ...inputs, paths3w: true });
      const alternatives = followupRequests(enabled, main);
      expect(plain.map((row) => row?.alternative.kind)).toEqual(["roll", "bank"]);
      expect(alternatives).toEqual(plain);
      const roll = alternatives[0]!.request;
      expect(restoredSlot(enabled, 0, { kind: "roll" })).toEqual(roll);
      const answer = structuredClone(envelope);
      Object.assign(answer.payload.plan_weeks![0]!, {
        transfers_in: [],
        transfers_out: [],
        free_transfers_after: 2,
      });
      const state = {
        phase: "done",
        request: roll,
        envelope: answer,
        source: "api-cache",
      } as const;
      expect(visibleAutomatic(state, main, [], true)?.kind).toBe("roll");
    },
  );

  it("starts every priced plan once the base is in", () => {
    const priced = run({
      hard: [],
      soft: [
        { kind: "include_player", player_id: 901 },
        { kind: "include_player", player_id: 902 },
      ],
    });
    expect(followupRequests(priced, plan)).toEqual([
      { request: priced.slots[0]!.request, alternative: { kind: "priced" } },
      { request: priced.slots[1]!.request, alternative: { kind: "priced" } },
    ]);
  });

  it("leaves a requested branch's slot to the branch", () => {
    const compared = run({
      hard: [],
      soft: [],
      comparison: { kind: "include_player", player_id: 901 },
    });
    const followups = followupRequests(compared, plan);
    expect(followups[0]).toBeNull();
    expect(followups.length).toBeLessThanOrEqual(ALTERNATIVE_COUNT);
  });
});
