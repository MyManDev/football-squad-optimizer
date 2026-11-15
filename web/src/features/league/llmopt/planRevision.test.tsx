import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import {
  checkedPlanRevision,
  freezeReference,
  referenceWeeks,
  summarizeRevision,
} from "./planRevision";
import { RevisionComparison } from "./RevisionComparison";

const ENTRY = 35249001;

afterEach(cleanup);

it("advertises available weeks, then freezes only the selected exact transfers, chip and lineup", () => {
  const plan = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3).payload;
  const captain = plan.captain!;
  const starters = plan.starting_xi!;
  const vice = plan.vice_captain!;
  const bench = plan.bench!;
  plan.plan_weeks![1] = {
    ...plan.plan_weeks![1]!,
    chip: "wildcard",
    lineup: { starting_xi: starters, captain, vice_captain: vice, bench },
  };
  const prior = summarizeRevision(plan)!;
  const restored = checkedPlanRevision(JSON.parse(JSON.stringify(prior)), plan.gameweek);

  expect(referenceWeeks(restored)).toEqual([1, 2, 3]);
  expect(freezeReference(restored)).toEqual([]);
  expect(freezeReference(restored, [2])).toEqual([
    {
      week: 2,
      transfers_in: plan.plan_weeks![1]!.transfers_in.map(({ player_id }) => player_id),
      transfers_out: plan.plan_weeks![1]!.transfers_out.map(({ player_id }) => player_id),
      chip: "wildcard",
      starting_xi: starters.map(({ player_id }) => player_id),
      captain: captain.player_id,
    },
  ]);
  expect(checkedPlanRevision(prior, plan.gameweek + 1)).toBeUndefined();
});

it("shows actual final bank and FTs without subtracting unequal planning horizons", () => {
  const old = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3).payload;
  const latest = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1).payload;
  old.bank_after_tenths = 49;
  old.plan_weeks![2] = { ...old.plan_weeks![2]!, bank_after_tenths: 12, free_transfers_after: 4 };
  latest.bank_after_tenths = 24;
  latest.free_transfers_after = 2;
  render(
    <LanguageProvider initialLanguage="en">
      <RevisionComparison previous={summarizeRevision(old)!} revised={summarizeRevision(latest)} />
    </LanguageProvider>,
  );
  const comparison = screen.getByRole("region", { name: "Plan revision" });
  const row = (name: string) => within(comparison).getByRole("row", { name: new RegExp(name) });
  const values = (name: string) =>
    within(row(name))
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
  expect(values("Budget after final week")).toEqual(["£1.2m", "£2.4m", "—"]);
  expect(values("Free transfers after final week")).toEqual(["4", "2", "—"]);
  expect(values("Total expected net points").at(-1)).toBe("—");
});
