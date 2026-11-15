import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { FIXTURES_QUERY } from "../../fixtures/data";
import type { EntryAdvice } from "../types";
import { PlanResult, type PreferencePrice } from "./PlanResult";

const ENTRY = 35249001;
const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
const example = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);

afterEach(cleanup);

function showWildcard(
  result: Partial<EntryAdvice>,
  baseline?: EntryAdvice,
  prices?: PreferencePrice[],
) {
  const client = new QueryClient();
  client.setQueryData(FIXTURES_QUERY.queryKey, null);
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage="en">
        <PlanResult
          title="Base plan"
          squad={squad}
          baseline={baseline}
          prices={prices}
          state={{
            phase: "done",
            source: "api-cache",
            request: {
              leagueId: squad.league_id,
              entryId: ENTRY,
              strategy: "saf-puan",
              window: result.window ?? 1,
              chip: "wildcard",
            },
            envelope: { ...example, payload: { ...example.payload, ...result, chip: "wildcard" } },
          }}
        />
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

it("shows the returned Wildcard squad on the member pitch, with its armbands and bench", () => {
  const captain = example.payload.captain!;
  const newCaptain = { ...captain, player_id: 90001, name: "Wildcard signing" };
  const eleven = example.payload.starting_xi!.map((player) =>
    player.player_id === captain.player_id ? newCaptain : player,
  );
  const { container } = showWildcard({ captain: newCaptain, starting_xi: eleven });
  const pitch = screen.getByRole("list", { name: "Starting Eleven by Position" });
  const bench = screen.getByRole("region", { name: "Bench" });

  expect(screen.getByText("Wildcard", { exact: true })).toBeVisible();
  expect(pitch.querySelectorAll("[data-player-motion]")).toHaveLength(11);
  expect(bench.querySelectorAll("[data-player-motion]")).toHaveLength(4);
  expect(container.querySelector(`[data-player-motion="${captain.player_id}"]`)).toBeNull();
  const armband = within(pitch).getByRole("img", { name: "captain" });
  expect(armband.closest('[data-player-motion="90001"]')).toHaveTextContent("Wildcard signing");
  expect(within(pitch).getByRole("img", { name: "vice-captain" })).toBeVisible();
});

it("displays an over-limit price at its measured precision and qualifies an unproved cost", () => {
  showWildcard({}, undefined, [
    {
      key: "saka",
      label: "Keep player · Saka",
      ceiling: 15,
      status: "priced",
      cost: 1.54,
      aboveCeiling: true,
      unproven: true,
    },
    { key: "roll", label: "Roll the transfer", status: "skipped" },
  ]);
  const review = screen.getByRole("region", { name: "Expected points cost of preferences" });
  expect(within(review).getByText(/1\.54 expected points lost · Up to 1\.5 points/)).toBeVisible();
  expect(within(review).getByText("Above your points limit.")).toBeVisible();
  expect(within(review).getByText("Cost is based on the plans found.")).toBeVisible();
  expect(
    within(review).getByText("This preference was not evaluated in this calculation."),
  ).toBeVisible();
});

it("shows when the Wildcard lineup is missing without using the held squad", () => {
  const { container } = showWildcard({ bench: null });

  expect(screen.getByText("Wildcard", { exact: true })).toBeVisible();
  expect(screen.getByText("The lineup for this plan is unavailable.")).toBeVisible();
  expect(container.querySelector("[data-player-motion]")).toBeNull();
});

it("compares total net points and displays upcoming transfers after the current pitch", () => {
  const { gameweek } = example.payload;
  const signing = { ...example.payload.starting_xi![0]!, name: "Next-week signing" };
  const weeks = [
    { gameweek, expected_points: 49, transfer_hit_points: 0, chip: "wildcard" },
    { gameweek: gameweek + 1, expected_points: 56, transfer_hit_points: 4, chip: null },
    { gameweek: gameweek + 2, expected_points: 51, transfer_hit_points: 0, chip: null },
  ] as const;
  showWildcard({
    window: 3,
    plan_weeks: weeks.map((week, index) => ({
      ...week,
      free_transfers_before: 1,
      free_transfers_after: index === 1 ? 1 : 2,
      transfers_in: index === 1 ? [signing] : [],
      transfers_out: [],
    })),
  });
  expect(screen.getByText("Total expected net points").nextElementSibling).toHaveTextContent(
    "152.0",
  );
  expect(screen.getByText("Total transfer penalty").nextElementSibling).toHaveTextContent("4");
  const upcoming = screen.getByRole("region", { name: "Upcoming weeks" });
  expect(within(upcoming).getByRole("heading", { name: `GW ${gameweek + 1}` })).toBeVisible();
  expect(within(upcoming).getByText(signing.name)).toBeVisible();
  expect(within(upcoming).getByRole("heading", { name: `GW ${gameweek + 2}` })).toBeVisible();
  expect(screen.getByRole("list", { name: "Starting Eleven by Position" })).toBeVisible();
});

it("shows net points, hit, bank and free-transfer differences against the reference plan", () => {
  const baseline: EntryAdvice = {
    ...example.payload,
    plan_weeks: null,
    lineup_expectation: undefined,
    expected_own_points: 43,
    transfer_hit_points: 0,
    bank_after_tenths: 12,
    free_transfers_after: 1,
  };
  showWildcard(
    {
      plan_weeks: null,
      lineup_expectation: undefined,
      expected_own_points: 45,
      transfer_hit_points: 4,
      bank_after_tenths: 16,
      free_transfers_after: 2,
    },
    baseline,
  );
  expect(screen.getByText("−2.0")).toBeVisible();
  expect(screen.getByText("Transfer penalty").nextElementSibling).toHaveTextContent("(+4)");
  expect(screen.getByText("Remaining budget").nextElementSibling).toHaveTextContent("(+£0.4m)");
  expect(screen.getByText("Free transfers next week").nextElementSibling).toHaveTextContent("(+1)");
});
