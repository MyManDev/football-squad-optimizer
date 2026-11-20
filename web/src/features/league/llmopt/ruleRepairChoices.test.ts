import { describe, expect, it } from "vitest";
import { checkedPreferences } from "../advice/decisionPreferences";
import type { PlanDraft } from "./intent";
import { ruleRepairChoices, repairSentence, type RuleRepairContext } from "./ruleRepairChoices";

const context: RuleRepairContext = {
  gameweek: 11,
  window: 3,
  held: new Set([1, 2]),
  heldClubs: new Map([
    [1, "Blue"],
    [2, "Red"],
  ]),
  frozen: [],
  language: "en",
  players: [
    { id: 1, name: "One", team: "Blue" },
    { id: 2, name: "Two", team: "Red" },
    { id: 3, name: "Three", team: "Blue" },
    { id: 4, name: "Four", team: "Red" },
  ],
  bankTenths: 26,
  freeTransfers: 1,
  hitPoints: 4,
};
const untouched: PlanDraft = {
  hard: [],
  soft: [{ kind: "keep_player", player_id: 1, priority: 2 }],
  max_total_cost_tenths: 0,
};

describe("verified repair candidates", () => {
  it.each(["en", "tr"] as const)("keeps separate localized outcomes in %s", (language) => {
    const messages = ["conflict", "missing", "budget"].map((status) =>
      repairSentence(language, status as "conflict" | "missing" | "budget"),
    );
    expect(new Set(messages).size).toBe(3);
    for (const sentence of messages) expect(sentence).toMatch(/^[^.!?]+\.$/);
  });
  it("changes only the timed club count incompatible with a fixed squad", () => {
    const draft: PlanDraft = {
      ...untouched,
      hard: [{ kind: "hold_transfers" }, { kind: "club_count", club: "Blue", count: 3, week: 2 }],
    };
    const choice = ruleRepairChoices(draft, context)!.choices[0]!;
    expect(choice.draft).toEqual({
      ...draft,
      hard: [draft.hard[0], { ...draft.hard[1], count: 1 }],
    });
    expect(choice.label).toContain("Blue");
    expect(choice.label).toContain("Week 2");
    expect(draft.hard[1]).toMatchObject({ count: 3 });
  });
  it("changes the member's matching bank floor without inventing a maximum", () => {
    const draft: PlanDraft = {
      ...untouched,
      hard: [{ kind: "hold_transfers", week: 1 }],
      min_bank: { tenths: 30, week: 1 },
    };
    expect(ruleRepairChoices(draft, context)?.choices[0]?.draft).toEqual({
      ...draft,
      min_bank: { tenths: 26, week: 1 },
    });
    const free: PlanDraft = { ...draft, hard: [] };
    expect(ruleRepairChoices(free, context)).toBeNull();
    expect(
      ruleRepairChoices(free, {
        ...context,
        failureCode: "PLAN_NOT_FOUND",
        diagnosis: { repairs: [], bank: { required: 30, reachable: 22, week: 1, exact: false } },
      })?.choices[0]?.draft.min_bank?.tenths,
    ).toBe(22);
  });
  it("raises the hit limit only for distinct forced buys beyond known available transfers", () => {
    const draft: PlanDraft = {
      ...untouched,
      hard: [
        { kind: "hit_budget", points: 0 },
        { kind: "buy_player", player_id: 3, week: 1 },
        { kind: "buy_player", player_id: 4, week: 1 },
        { kind: "include_player", player_id: 3 },
      ],
    };
    expect(ruleRepairChoices(draft, context)?.choices[0]?.draft).toEqual({
      ...draft,
      hard: [{ kind: "hit_budget", points: 4 }, ...draft.hard.slice(1)],
    });
    expect(ruleRepairChoices(draft, { ...context, freeTransfers: null })).toBeNull();
    expect(ruleRepairChoices(draft, { ...context, hitPoints: null })).toBeNull();
    expect(ruleRepairChoices(draft, { ...context, hitPoints: 0 })).toBeNull();
    expect(
      ruleRepairChoices(
        { ...draft, hard: [{ kind: "no_hits" }, ...draft.hard.slice(1)] },
        { ...context, hitPoints: null },
      )?.status,
    ).toBe("conflict");
    expect(
      ruleRepairChoices({ ...draft, hard: [...draft.hard, { kind: "wildcard" }] }, context),
    ).toBeNull();
  });
  it("unlocks only the affected week and does not mistake an absent reference for a conflict", () => {
    const draft: PlanDraft = {
      ...untouched,
      keep_weeks: [1, 2],
      hard: [{ kind: "buy_player", player_id: 3, week: 2 }],
    };
    const fixed = { transfers_in: [], transfers_out: [], chip: null };
    expect(
      ruleRepairChoices(draft, {
        ...context,
        frozen: [
          { week: 1, ...fixed },
          { week: 2, ...fixed },
        ],
      })?.choices,
    ).toEqual([{ draft: { ...draft, keep_weeks: [1] }, label: "Unlock GW 12" }]);
    expect(ruleRepairChoices(draft, context)).toMatchObject({ status: "missing", choices: [] });
  });
  it("distinguishes absent chip rights, unknown history, and a right in a different week", () => {
    const draft: PlanDraft = { ...untouched, hard: [{ kind: "wildcard" }] };
    expect(ruleRepairChoices(draft, { ...context, heldChips: [] })?.choices[0]?.draft).toEqual(
      untouched,
    );
    expect(ruleRepairChoices(draft, { ...context, heldChips: null })).toMatchObject({
      status: "missing",
      choices: [],
    });
    expect(ruleRepairChoices(draft, { ...context, heldChips: ["wildcard"] })).toBeNull();
    expect(
      ruleRepairChoices(
        { ...draft, hard: [{ kind: "wildcard", week: 3 }] },
        { ...context, heldChips: [] },
      ),
    ).toBeNull();
  });
  it("only returns candidates after a known contradiction or a verified infeasibility", () => {
    const draft: PlanDraft = {
      ...untouched,
      min_bank: { tenths: 44 },
      hard: [
        { kind: "club_count", club: "Blue", count: 2 },
        { kind: "hit_budget", points: 8 },
      ],
    };
    expect(ruleRepairChoices(draft, context)).toBeNull();
    expect(ruleRepairChoices(draft, { ...context, failureCode: "PLAN_NOT_FOUND" })).toBeNull();
    expect(
      ruleRepairChoices(draft, {
        ...context,
        failureCode: "ADVICE_FAILED",
        diagnosis: { repairs: [] },
      }),
    ).toBeNull();
    expect(
      ruleRepairChoices(draft, { ...context, failureCode: "DEVICE_INPUTS_UNAVAILABLE" }),
    ).toMatchObject({ status: "missing", choices: [] });
    expect(
      ruleRepairChoices(draft, { ...context, failureCode: "RUN_BUDGET_EXHAUSTED" }),
    ).toMatchObject({ status: "budget", choices: [] });
    expect(
      ruleRepairChoices(draft, { ...context, failureCode: "PATIENCE_EXHAUSTED" }),
    ).toMatchObject({
      status: "budget",
      choices: [],
      sentence: "The wait for this plan timed out.",
    });
    expect(
      ruleRepairChoices(draft, {
        ...context,
        failureCode: "PLAN_NOT_FOUND",
        diagnosis: { repairs: [] },
      })?.choices,
    ).toHaveLength(2);
  });
  it("revalidates both original purchase repairs against the failed hard purchase", () => {
    const buy = { kind: "buy_player", week: 1, player_id: 3 } as const;
    const draft: PlanDraft = { ...untouched, hard: [buy] };
    const diagnosis = {
      repairs: [
        { kind: "defer_purchase", from_week: 1, to_week: 2, player_id: 3 },
        { kind: "release_purchase", week: 1, player_id: 3 },
      ],
    } as const;
    const request = {
      leagueId: 1,
      entryId: 1,
      strategy: "saf-puan",
      window: 3,
      preferences: checkedPreferences({ week_rules: [{ week: 1, rules: { buy_players: [3] } }] }),
    } as const;
    const input = {
      ...context,
      failureCode: "PLAN_NOT_FOUND",
      request,
      diagnosis: { repairs: [...diagnosis.repairs] },
    };
    const result = ruleRepairChoices(draft, input);
    expect(result?.choices.map((c) => c.draft.hard)).toEqual([[{ ...buy, week: 2 }], []]);
    expect(result?.choices.map((c) => c.label)).toEqual([
      "Move the Three transfer from GW 11 to GW 12",
      "Remove the Three transfer rule in GW 11",
    ]);
    expect(result?.choices.every((c) => c.draft.soft[0]?.priority === 2)).toBe(true);
    expect(
      ruleRepairChoices(draft, {
        ...input,
        request: { ...request, preferences: checkedPreferences({}) },
      })?.choices,
    ).toEqual([]);
  });
});
