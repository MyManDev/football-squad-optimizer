import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";
import fixture from "../../../fixtures/weeklySuggestionHistory.json";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import { claimIn, forgetIdentity } from "../../../testSupport/league";
import { checkedHistory, type SuggestionHistory } from "./historyData";
import { PersonalSeasonReport } from "./PersonalSeasonReport";

afterEach(() => {
  cleanup();
  forgetIdentity();
});

function report() {
  const value = structuredClone(fixture) as SuggestionHistory;
  value.payload.weeks[0].actual!.details = {
    source_snapshot_id: "settled-capture",
    captain: { player_id: 8, name: "Captain", points: 3, multiplier: 2, counted_points: 6 },
    transfers: [
      {
        player_out: "Former one",
        player_in: {
          player_id: 1,
          name: "Arrival one",
          points: 5,
          multiplier: 1,
          counted_points: 5,
        },
      },
      {
        player_out: "Former two",
        player_in: {
          player_id: 2,
          name: "Arrival two",
          points: 2,
          multiplier: 0,
          counted_points: 0,
        },
      },
    ],
  };
  return checkedHistory(value, 101, 352490);
}

function show(value: SuggestionHistory, language: Language = "tr") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <PersonalSeasonReport history={value} />
    </LanguageProvider>,
  );
}

it.each<Language>(["tr", "en"])(
  "shows two transfers, the counted captain and net totals in %s",
  async (language) => {
    claimIn(101, 352490);
    show(report(), language);
    const title = screen.getByText(language === "tr" ? "Sezon raporum" : "My season report");
    expect(title.closest("details")).not.toHaveAttribute("open");
    await userEvent.click(title);
    const week = screen.getByRole("region", { name: language === "tr" ? "Hafta 4" : "Gameweek 4" });
    expect(week).toHaveTextContent(/22[,.]0.*20[,.]0.*8[,.]0/);
    expect(week).toHaveTextContent(/Captain.*6[,.]0/);
    const moves = within(week).getAllByRole("listitem");
    expect(moves).toHaveLength(2);
    expect(moves[0]).toHaveTextContent(/Former one → Arrival one.*5[,.]0/);
    expect(moves[1]).toHaveTextContent(/Former two → Arrival two.*0[,.]0/);
  },
);

it.each([null, 202])("does not show another member's report (claim %s)", (entry) => {
  if (entry !== null) claimIn(entry, 352490);
  expect(show(report()).container).toBeEmptyDOMElement();
});

it("keeps older settled totals without inventing captain or transfer details", async () => {
  claimIn(101, 352490);
  const value = report();
  delete value.payload.weeks[0].actual!.details;
  show(value);
  await userEvent.click(screen.getByText("Sezon raporum"));
  expect(screen.getByText("Kadro puanım")).toBeVisible();
  expect(screen.queryByText("Kaptan")).not.toBeInTheDocument();
  expect(screen.queryByText("Transferlerim")).not.toBeInTheDocument();
});

it("does not render an unsettled week even if a caller supplies partial values", () => {
  claimIn(101, 352490);
  const value = report();
  value.payload.weeks[0].status = "unsettled";
  expect(show(value).container).toBeEmptyDOMElement();
});

it.each([NaN, 9, -1, 1.5])("refuses an inconsistent captain multiplier %s", (multiplier) => {
  const value = report();
  value.payload.weeks[0].actual!.details!.captain.multiplier = multiplier;
  expect(() => checkedHistory(value, 101, 352490)).toThrow();
});

it("refuses double-counting an incoming player", () => {
  const value = report();
  const moves = value.payload.weeks[0].actual!.details!.transfers;
  moves.push(structuredClone(moves[0]));
  expect(() => checkedHistory(value, 101, 352490)).toThrow();
});
