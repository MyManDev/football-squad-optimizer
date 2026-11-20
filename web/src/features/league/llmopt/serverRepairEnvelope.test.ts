import { expect, it } from "vitest";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { adviceRequestBody, type AdviceRequest } from "../advice/adviceClient";
import { type PlanWeekNumber } from "../advice/decisionPreferences";
import { type Constraint, type PlanDraft } from "./intent";
import { summarizeRevision } from "./planRevision";
import { candidateRequest, verificationRequest } from "./repairComputation";

const team = mockEntrySquadEnvelopes[35249001]!.payload;
const squad = {
  ...team,
  starting_xi: team.starting_xi.map((p, i) => ({ ...p, player_id: 300 + i })),
  bench: team.bench.map((p, i) => ({ ...p, player_id: 311 + i })),
};
const example = mockEntryAdviceEnvelope(35249001, "saf-puan", 3).payload;
const starters = example.starting_xi!.map((p, i) => ({ ...p, player_id: 300 + i }));
const lineup = {
  starting_xi: starters,
  captain: starters[0]!,
  vice_captain: starters[1]!,
  bench: example.bench!,
};
const witness = {
  ...example,
  plan_weeks: example.plan_weeks!.map((w) => ({
    ...w,
    transfers_in: [],
    transfers_out: [],
    chip: null,
    lineup,
  })),
};
const owner = { runId: "a".repeat(32), dataId: "b".repeat(64), failedBase: false };
const basis = { squad, window: 3 as const, reference: summarizeRevision(witness) };
const bytes = (request: AdviceRequest) =>
  new TextEncoder().encode(adviceRequestBody(request)).byteLength;

it.each([false, true])(
  "fits 16 original rules plus the selected lineup with fixed weeks %s",
  (fixed) => {
    const hard: Constraint[] = [
      { kind: "club_count", club: "Arsenal", week: 1, count: 2 },
      { kind: "club_count", club: "Arsenal", week: 1, count: 1 },
      ...Array.from({ length: 14 }, (_, i) => ({
        kind: "keep_player" as const,
        player_id: 300 + i,
        week: (1 + (i % 3)) as PlanWeekNumber,
      })),
    ];
    const sourceDraft: PlanDraft = {
      window: 3,
      soft: [],
      hard,
      ...(fixed ? { keep_weeks: [1, 2, 3] } : {}),
    };
    const request = candidateRequest(
      { ...sourceDraft, hard: hard.slice(1) },
      basis,
      { ...owner, sourceDraft },
      "base",
    )!;
    const candidate = { ...request, model: "football" as const };
    const verify = verificationRequest(candidate, witness)!;
    const scoped = candidate.run!.repair_origin!.preferences.flatMap((p) => p.week_rules ?? []);
    expect(scoped).toHaveLength(16);
    expect(scoped.every((row) => Object.keys(row.rules).length === 1)).toBe(true);
    expect(verify.preferences.frozen_weeks).toHaveLength(3);
    expect(verify.preferences.frozen_weeks!.every((w) => w.starting_xi?.length === 11)).toBe(true);
    expect(bytes(candidate)).toBeLessThanOrEqual(4096);
    expect(bytes(verify)).toBeLessThanOrEqual(4096);
  },
);

it("checks UTF-8 bytes before posting candidates and before offering a witness for replay", () => {
  function envelope(padding: number) {
    const rules: Constraint[] = Array.from({ length: 14 }, (_, i) => ({
      kind: "club_count",
      club: "Ş".repeat(padding) + i,
      count: 1,
    }));
    const sourceDraft: PlanDraft = { window: 3, hard: [...rules, { kind: "no_hits" }], soft: [] };
    return candidateRequest(
      { ...sourceDraft, hard: rules },
      basis,
      { ...owner, sourceDraft },
      "base",
    )!;
  }
  expect(() => envelope(70)).toThrow("RUN_REPAIR_INVALID");
  // Find the valid candidate closest to the actual wire limit; no assumed roster size.
  let last = envelope(1);
  for (let width = 2; width <= 70; width++) {
    try {
      last = envelope(width);
    } catch (error) {
      expect(error).toEqual(new Error("RUN_REPAIR_INVALID"));
      break;
    }
  }
  expect(bytes(last)).toBeLessThanOrEqual(4096);
  expect(() => verificationRequest(last, witness)).toThrow("RUN_REPAIR_INVALID");
});
