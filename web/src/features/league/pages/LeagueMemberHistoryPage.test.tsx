import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it } from "vitest";
import fixture from "../../../fixtures/weeklySuggestionHistory.json";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { type Language, MESSAGES } from "../../../i18n/messages";
import type { SuggestionHistory } from "../history/historyData";
import { LeagueMemberHistoryView } from "./LeagueMemberHistoryPage";

afterEach(cleanup);
const history = () => structuredClone(fixture) as SuggestionHistory;
function show(value = history(), language: Language = "tr") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter>
        <LeagueMemberHistoryView history={value} />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

it.each<Language>(["tr", "en"])(
  "shows gross, costs, net and a signed comparison in %s",
  (language) => {
    show(history(), language);
    const copy = MESSAGES[language].suggestionHistory;
    expect(screen.getByRole("heading", { name: copy.title })).toBeInTheDocument();
    const table = screen.getByRole("region", { name: copy.title });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent(/24[,.]0.*30[,.]0/);
    expect(rows[2]).toHaveTextContent(/4[,.]0.*8[,.]0/);
    expect(rows[3]).toHaveTextContent(/20[,.]0.*22[,.]0/);
    expect(screen.getByText(`${copy.difference}:`).textContent).toMatch(/−2[,.]0/);
    expect(screen.getByText(copy.expectationNote)).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: copy.players })).getAllByRole("row"),
    ).toHaveLength(16);
  },
);

it("labels unknown actual scores without suggesting a zero-point result", () => {
  const value = history();
  Object.assign(value.payload.weeks[0], {
    actual: null,
    net_difference: null,
    actual_reason: "actual_score_missing",
  });
  show(value);
  expect(screen.getByText(MESSAGES.tr.suggestionHistory.actualMissing)).toBeInTheDocument();
  const table = screen.getByRole("region", { name: MESSAGES.tr.suggestionHistory.title });
  expect(within(table).getAllByText("—")).toHaveLength(3);
});

it("switches only between recorded weeks and hides unsettled scores", async () => {
  const value = history();
  value.payload.weeks.unshift({
    ...value.payload.weeks[0],
    gameweek: 5,
    status: "unsettled",
    reason: "not_settled",
    suggested: null,
    actual: null,
    net_difference: null,
    players: [],
  });
  show(value);
  const copy = MESSAGES.tr.suggestionHistory;
  expect(screen.getByText(copy.unsettled)).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.getAllByRole("option")).toHaveLength(2);
  await userEvent.selectOptions(screen.getByRole("combobox", { name: copy.week }), "4");
  expect(screen.getAllByRole("table")).toHaveLength(2);
  expect(screen.queryByText(copy.unsettled)).not.toBeInTheDocument();
});

it("shows no-record state without creating any historical weeks", () => {
  const value = history();
  value.payload.weeks = [];
  show(value);
  expect(screen.getByText(MESSAGES.tr.suggestionHistory.empty)).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
