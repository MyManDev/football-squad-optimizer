import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { FIXTURES_QUERY } from "../../fixtures/data";
import type { EntryAdvice } from "../types";
import { PlanResult } from "./PlanResult";

const ENTRY = 35249001;
const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
const example = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);

afterEach(cleanup);

function showWildcard(result: Partial<EntryAdvice>) {
  const client = new QueryClient();
  client.setQueryData(FIXTURES_QUERY.queryKey, null);
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage="en">
        <PlanResult
          title="Base plan"
          squad={squad}
          state={{
            phase: "done",
            source: "api-cache",
            request: {
              leagueId: squad.league_id,
              entryId: ENTRY,
              strategy: "saf-puan",
              window: 1,
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

it("shows when the Wildcard lineup is missing without using the held squad", () => {
  const { container } = showWildcard({ bench: null });

  expect(screen.getByText("Wildcard", { exact: true })).toBeVisible();
  expect(screen.getByText("The lineup for this plan is unavailable.")).toBeVisible();
  expect(container.querySelector("[data-player-motion]")).toBeNull();
});
