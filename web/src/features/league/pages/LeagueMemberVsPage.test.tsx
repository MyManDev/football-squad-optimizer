/**
 * VS SQUADOPT: each settled week the history holds a suggestion and a result for, the
 * system's captain, moves and net beside the member's, with the difference, and the
 * season's totals above. A week without both sides is left out.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/weeklySuggestionHistory.json";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { withLeague } from "../../../testSupport/league";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import type { SuggestionHistory, WeekReview } from "../history/historyData";
import { LeagueMemberVsView } from "./LeagueMemberVsPage";

afterEach(cleanup);

const BASE = fixture as unknown as SuggestionHistory;
const WEEK = BASE.payload.weeks[0]!;

/** The fixture's week with the details both sides need, and a second week in reverse. */
function history(): SuggestionHistory {
  const four: WeekReview = {
    ...WEEK,
    gameweek: 4,
    recorded_plans: [
      {
        published_path: "advice/101/saf-puan/1.json",
        strategy: "saf-puan",
        window: 1,
        rival_entry_id: null,
        chip: null,
        captain: "Player 8",
        moves: [{ player_out: "Player 20", player_in: "Player 8" }],
      },
    ],
    actual: {
      gross_points: 30,
      transfer_hit_points: 8,
      net_points: 22,
      details: {
        source_snapshot_id: "fpl-live-outcome",
        captain: { player_id: 9, name: "Player 9", points: 6, multiplier: 2, counted_points: 12 },
        transfers: [
          {
            player_out: "Player 21",
            player_in: {
              player_id: 3,
              name: "Player 3",
              points: 2,
              multiplier: 1,
              counted_points: 2,
            },
          },
          {
            player_out: "Player 22",
            player_in: {
              player_id: 5,
              name: "Player 5",
              points: 1,
              multiplier: 1,
              counted_points: 1,
            },
          },
        ],
      },
    },
  };
  const five: WeekReview = {
    ...WEEK,
    gameweek: 5,
    suggested: { ...WEEK.suggested!, net_points: 40, gross_points: 40, transfer_hit_points: 0 },
    actual: { gross_points: 35, transfer_hit_points: 0, net_points: 35, details: null },
    net_difference: 5,
    recorded_plans: [],
  };
  const six: WeekReview = {
    ...WEEK,
    gameweek: 6,
    status: "unsettled",
    suggested: null,
    actual: null,
    net_difference: null,
    players: [],
  };
  return { ...BASE, payload: { ...BASE.payload, weeks: [four, six, five] } };
}

function open(language: "tr" | "en", document: SuggestionHistory) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/352490/members/101/vs`]}>
        {withLeague(<LeagueMemberVsView history={document} />)}
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe.each(["tr", "en"] as const)("VS SQUADOPT in %s", (language) => {
  const copy = MESSAGES[language].vsSquadopt;

  it("draws each compared week, latest first, with both sides' captain, moves and net", () => {
    open(language, history());
    expect(screen.getByRole("heading", { level: 1, name: copy.title })).toBeInTheDocument();
    const weeks = screen.getAllByTestId("vs-week");
    expect(weeks).toHaveLength(2);
    expect(weeks[0]).toHaveTextContent(MESSAGES[language].suggestionHistory.gameweek(5));
    const four = within(weeks[1]!);
    expect(four.getAllByText("Player 8").length).toBeGreaterThan(0);
    expect(four.getByText("Player 9")).toBeInTheDocument();
    expect(four.getByText("Player 3")).toBeInTheDocument();
    expect(four.getByText("Player 5")).toBeInTheDocument();
    expect(weeks[1]).toHaveTextContent("Player 20 →");
    expect(weeks[1]).toHaveTextContent(`${copy.difference}: −2`);
    expect(weeks[0]).toHaveTextContent(copy.none);
    expect(weeks[0]).toHaveTextContent("—");
  });

  it("sums the compared weeks above, and names how many", () => {
    open(language, history());
    const totals = screen.getByTestId("vs-totals");
    expect(totals).toHaveTextContent("60");
    expect(totals).toHaveTextContent("57");
    expect(totals).toHaveTextContent("+3");
    expect(document.body.textContent).not.toMatch(AS_A_CHANCE);
    expect(document.body.textContent).not.toMatch(AS_A_CAVEAT);
  });

  it("says there is no record where no week has both sides", () => {
    const document = history();
    document.payload.weeks = [document.payload.weeks[1]!];
    open(language, document);
    expect(screen.getByText(MESSAGES[language].suggestionHistory.empty)).toBeInTheDocument();
  });
});
