import { expect, it } from "vitest";

import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { checkedPreferences } from "../advice/decisionPreferences";
import type { ComputePhase } from "../advice/useAdviceJob";
import type { AdvicePlanWeek, EntryAdvice } from "../types";
import {
  meaningfulOpeningAlternative,
  openingAlternatives,
  sameOpeningDecision,
  samePlan,
} from "./planComparison";

const example = mockEntryAdviceEnvelope(35249001, "saf-puan", 3);
const fixture = example.payload;
const outgoing = fixture.starting_xi![0]!;
const incoming = { ...outgoing, player_id: 991 };
const opening: AdvicePlanWeek = {
  gameweek: fixture.gameweek,
  transfers_in: [incoming],
  transfers_out: [outgoing],
  chip: null,
  free_transfers_before: 1,
  free_transfers_after: 1,
  transfer_hit_points: 0,
  expected_points: 48,
};

function plan(week: Partial<AdvicePlanWeek> = {}, fields: Partial<EntryAdvice> = {}): EntryAdvice {
  return { ...fixture, bank_after_tenths: 20, plan_weeks: [{ ...opening, ...week }], ...fields };
}

it("adds explicit opening-only objectives while preserving the confirmed rules", () => {
  const reference = checkedPreferences({
    no_hits: true,
    keep_players: [992],
    wildcard_week: 2,
    max_hit_points: 0,
    week_rules: [{ week: 2, rules: { buy_players: [993] } }],
  });
  expect(openingAlternatives(plan(), reference, null)).toEqual({
    roll: { ...reference, hold_opening_transfers: true },
    bank: { ...reference, min_opening_bank_tenths: 21 },
  });
});

it("skips the opening hold when it duplicates or conflicts with a required decision", () => {
  for (const rules of [
    { hold_transfers: true },
    { hold_opening_transfers: true },
    { week_rules: [{ week: 1, rules: { hold_transfers: true } }] },
    { week_rules: [{ week: 1, rules: { buy_players: [incoming.player_id] } }] },
    { club_counts: [{ club: "Brighton", count: 3, scope: "transfers_in" }] },
    { include_players: [incoming.player_id] },
    { week_rules: [{ week: 1, rules: { avoid_players: [outgoing.player_id] } }] },
  ]) {
    expect(openingAlternatives(plan(), checkedPreferences(rules), null).roll).toBeNull();
  }
  const plain = checkedPreferences({});
  expect(openingAlternatives(plan(), plain, "wildcard").roll).toBeNull();
  expect(openingAlternatives(plan({ chip: "freehit" }), plain, null).roll).toBeNull();
  expect(
    openingAlternatives(plan({ transfers_in: [], transfers_out: [] }), plain, null).roll,
  ).toBeNull();
  expect(
    openingAlternatives(plan({}, { bank_after_tenths: undefined }), plain, null).bank,
  ).toBeNull();
  expect(openingAlternatives(plan({}, { bank_after_tenths: 10_000 }), plain, null).bank).toBeNull();
  for (const rules of [
    { hold_transfers: true },
    { hold_opening_transfers: true },
    { week_rules: [{ week: 1, rules: { hold_transfers: true } }] },
  ]) {
    expect(openingAlternatives(plan(), checkedPreferences(rules), null).bank).toBeNull();
  }
});

it("ignores order, lineups and armbands when comparing the opening transfers and chip", () => {
  const next = { ...incoming, player_id: 9001 };
  const sold = { ...outgoing, player_id: 9002 };
  const base = plan({ transfers_in: [incoming, next], transfers_out: [outgoing, sold] });
  const same = plan(
    { transfers_in: [next, incoming], transfers_out: [sold, outgoing] },
    { bank_after_tenths: 35, captain: next, starting_xi: [...fixture.starting_xi!].reverse() },
  );
  expect(sameOpeningDecision(base, same)).toBe(true);
  expect(meaningfulOpeningAlternative(base, same, "bank")).toBe(false);
  expect(sameOpeningDecision(base, plan({ ...base.plan_weeks![0], chip: "wildcard" }))).toBe(false);
});

it("requires a resource gain and a different opening in the same planning context", () => {
  const stayed = { transfers_in: [], transfers_out: [] };
  const base = plan();
  expect(meaningfulOpeningAlternative(base, plan(stayed), "roll")).toBe(false);
  const rolled = plan({ ...stayed, free_transfers_after: 2 });
  expect(meaningfulOpeningAlternative(base, rolled, "roll")).toBe(true);
  expect(meaningfulOpeningAlternative(plan({ transfer_hit_points: 4 }), plan(stayed), "roll")).toBe(
    true,
  );
  expect(meaningfulOpeningAlternative(base, { ...rolled, window: 1 }, "roll")).toBe(false);
  expect(meaningfulOpeningAlternative(base, rolled, "bank")).toBe(false);
  expect(meaningfulOpeningAlternative(base, { ...rolled, bank_after_tenths: 21 }, "bank")).toBe(
    true,
  );
});

it("deduplicates explicit branches with the same transfers while retaining different future decisions", () => {
  const weeks = [0, 1, 2].map((offset) => ({
    ...opening,
    gameweek: fixture.gameweek + offset,
  }));
  const done = (payload: EntryAdvice): ComputePhase => ({
    phase: "done",
    source: "api-cache",
    request: {
      entryId: fixture.entry_id,
      leagueId: fixture.league_id,
      strategy: "saf-puan",
      window: 3,
    },
    envelope: { ...example, payload },
  });
  const base = done(plan({}, { plan_weeks: weeks }));
  const differentLineup = done(
    plan(
      {},
      {
        plan_weeks: weeks,
        bench: [...fixture.bench!].reverse(),
        captain: incoming,
      },
    ),
  );
  expect(samePlan(base, differentLineup)).toBe(true);
  const laterTransfer = done(
    plan(
      {},
      {
        plan_weeks: weeks.map((week, index) =>
          index === 1 ? { ...week, transfers_in: [{ ...incoming, player_id: 921 }] } : week,
        ),
      },
    ),
  );
  expect(samePlan(base, laterTransfer)).toBe(false);
});
