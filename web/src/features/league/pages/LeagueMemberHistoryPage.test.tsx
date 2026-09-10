import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it } from "vitest";
import fixture from "../../../fixtures/weeklySuggestionHistory.json";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { type Language, MESSAGES } from "../../../i18n/messages";
import type { SuggestionHistory } from "../history/historyData";
import { LeagueMemberHistoryView } from "./LeagueMemberHistoryPage";
import { mockSuggestionOverview } from "../../../fixtures/weeklySuggestionOverview";

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
  async (language) => {
    show(history(), language);
    const copy = MESSAGES[language].suggestionHistory;
    await userEvent.selectOptions(screen.getByRole("combobox", { name: copy.week }), "4");
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

it("labels unknown actual scores without suggesting a zero-point result", async () => {
  const value = history();
  Object.assign(value.payload.weeks[0], {
    actual: null,
    net_difference: null,
    actual_reason: "actual_score_missing",
  });
  show(value);
  await userEvent.selectOptions(screen.getByRole("combobox"), "4");
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
  expect(screen.getByRole("combobox")).toHaveValue("overview");
  await userEvent.selectOptions(screen.getByRole("combobox"), "5");
  expect(screen.getByText(copy.unsettled)).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.getAllByRole("option")).toHaveLength(3);
  await userEvent.selectOptions(screen.getByRole("combobox", { name: copy.week }), "4");
  expect(screen.getAllByRole("table")).toHaveLength(2);
  expect(screen.queryByText(copy.unsettled)).not.toBeInTheDocument();
});

it("opens all recorded weeks by default, shows totals, and returns from a selected week", async () => {
  show(mockSuggestionOverview());
  const overview = screen.getByRole("region", { name: "Genel bakış" });
  expect(within(overview).getAllByRole("row")).toHaveLength(13);
  expect(
    within(within(overview).getByRole("row", { name: /^Toplam/ }))
      .getAllByRole("cell")
      .map((cell) => cell.textContent),
  ).toEqual(["624,0", "610,0", "+14,0", "+14,0"]);
  expect(screen.getByText("11 kayıtlı haftanın 9 tanesi karşılaştırıldı")).toBeInTheDocument();
  await userEvent.click(within(overview).getByRole("button", { name: "Oyun haftası 5" }));
  expect(screen.getByRole("combobox")).toHaveValue("5");
  expect(screen.queryByRole("region", { name: "Genel bakış" })).not.toBeInTheDocument();
  expect(screen.getByText("Önerinin neti − üyenin neti:")).toHaveTextContent("+6,0");
  await userEvent.selectOptions(screen.getByRole("combobox"), "overview");
  expect(screen.getByRole("region", { name: "Genel bakış" })).toBeInTheDocument();
});

it("shows no-record state without creating any historical weeks", () => {
  const value = history();
  value.payload.weeks = [];
  show(value);
  expect(screen.getByText(MESSAGES.tr.suggestionHistory.empty)).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
