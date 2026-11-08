/**
 * VS SQUADOPT, one week in detail: the sentence that says what the member would have scored
 * with the plan against what they scored, what the plan said beside what the member did,
 * where the difference came from, and SquadOpt's squad with its points. The latest settled
 * week opens first; the selector moves to another.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/weeklySuggestionHistory.json";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { withLeague } from "../../../testSupport/league";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import type { SuggestionHistory, WeekReview } from "../history/historyData";
import { LeagueMemberVsView } from "./LeagueMemberVsPage";
import { breakdown } from "./vsBreakdown";

afterEach(cleanup);

const BASE = fixture as unknown as SuggestionHistory;
const WEEK = BASE.payload.weeks[0]!;

/** Week 4 with both sides in detail, week 5 with totals only, week 6 unsettled. */
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
      {
        published_path: "advice/101/fark-yarat/3.json",
        strategy: "fark-yarat",
        window: 3,
        rival_entry_id: 102,
        chip: null,
        captain: "Player 2",
        moves: [{ player_out: "Player 20", player_in: "Player 2" }],
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
  const weekWord = MESSAGES[language].suggestionHistory.gameweek;

  it("opens on the latest settled week, says what the plan would have scored, and offers the other weeks", async () => {
    open(language, history());
    expect(screen.getByRole("heading", { level: 1, name: copy.title })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: weekWord(5) })).toBeInTheDocument();
    // Week 5: the plan 40, the member 35, in SquadOpt's favour.
    expect(screen.getByTestId("vs-headline")).toHaveTextContent(copy.wouldHave("40", "35"));
    expect(screen.getByText(copy.favoursSquadopt)).toBeInTheDocument();
    expect(screen.getByText(copy.noDetails)).toBeInTheDocument();
    expect(screen.queryByTestId("vs-breakdown")).toBeNull();
    expect(screen.getByTestId("vs-net-bars")).toBeInTheDocument();
    const strip = within(screen.getByTestId("vs-week-strip"));
    const weeksInStrip = strip.getAllByRole("button");
    expect(weeksInStrip.map((b) => b.getAttribute("aria-pressed"))).toEqual(["false", "true"]);
    expect(weeksInStrip[1]).toHaveAccessibleName(`${weekWord(5)}, +5`);
    await userEvent.click(weeksInStrip[0]!);
    expect(screen.getByRole("heading", { level: 2, name: weekWord(4) })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(AS_A_CHANCE);
    expect(document.body.textContent).not.toMatch(AS_A_CAVEAT);
  });

  it("shows, for a week with details, what the plan said, what the member did, the other plans and the squad", async () => {
    open(language, history());
    await userEvent.click(within(screen.getByTestId("vs-week-strip")).getAllByRole("button")[0]!);
    // Week 4: the plan 20, the member 22, in the member's favour.
    expect(screen.getByTestId("vs-headline")).toHaveTextContent(copy.youBeat("22", "20"));
    expect(screen.getByText(copy.favoursYou)).toBeInTheDocument();
    const said = within(screen.getByRole("heading", { name: copy.said }).closest("section")!);
    expect(said.getAllByText(/Player 20 →/).length).toBeGreaterThan(0);
    expect(said.getAllByText("Player 8").length).toBeGreaterThan(0);
    expect(said.getByText(copy.planName("fark-yarat", 3))).toBeInTheDocument();
    const did = within(screen.getByRole("heading", { name: copy.did }).closest("section")!);
    expect(did.getByText("Player 9")).toBeInTheDocument();
    expect(did.getByText("Player 3")).toBeInTheDocument();
    expect(did.getByText("Player 5")).toBeInTheDocument();
    expect(screen.getByTestId("vs-breakdown")).toBeInTheDocument();
    expect(screen.getByTestId("vs-difference-bars")).toBeInTheDocument();
    const squad = screen.getByRole("region", { name: copy.squad });
    expect(within(squad).getAllByRole("row").length).toBeGreaterThan(11);
  });

  it("says there is no record where no week has both sides", () => {
    const document = history();
    document.payload.weeks = [document.payload.weeks[1]!];
    open(language, document);
    expect(screen.getByText(MESSAGES[language].suggestionHistory.empty)).toBeInTheDocument();
  });
});

describe("where the difference came from", () => {
  it("splits the week's difference into captain, transfers, hits and the rest, which add up", () => {
    const week = history().payload.weeks[0]!;
    const parts = breakdown(week)!;
    // Captain: the plan's bonus (2) less the member's (12 counted − 6 points = 6).
    expect(parts.captain).toBe(2 - 6);
    // Transfers: the plan brought in Player 8 (his points that week) less the member's two.
    const eight = week.players.find((player) => player.name === "Player 8")!.realized_points;
    expect(parts.transfers).toBe(eight - 3);
    // Hits: the member paid 8, the plan 4; the plan saved 4.
    expect(parts.hits).toBe(4);
    expect(parts.captain + parts.transfers + parts.hits + parts.lineup).toBeCloseTo(
      week.net_difference!,
      9,
    );
  });

  it("is nothing without the member's details", () => {
    expect(breakdown(history().payload.weeks[2]!)).toBeNull();
  });
});
