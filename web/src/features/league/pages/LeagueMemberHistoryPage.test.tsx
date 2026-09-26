import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it } from "vitest";
import fixture from "../../../fixtures/weeklySuggestionHistory.json";
import planRows from "../../../fixtures/recordedPlanRows.json";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { type Language, MESSAGES } from "../../../i18n/messages";
import type { SuggestionHistory } from "../history/historyData";
import { LeagueMemberHistoryView } from "./LeagueMemberHistoryPage";
import { mockSuggestionOverview } from "../../../fixtures/weeklySuggestionOverview";
import { TOP100_COPY } from "../advice/top100Copy";
import { mockMembers } from "../../../fixtures/league";
import type { EntryView } from "../types";

afterEach(cleanup);
it.each<Language>(["tr", "en"])(
  "keeps archived plans collapsed and old prices absent in %s",
  async (language) => {
    const value = history();
    Object.assign(value.payload.weeks[0], { recorded_plans: planRows });
    show(value, language);
    const copy = MESSAGES[language].suggestionHistory;
    await userEvent.selectOptions(screen.getByRole("combobox"), "4");
    const summary = screen.getByText(copy.recordedPlans);
    const section = summary.closest("details")!;
    expect(section).not.toHaveAttribute("open");
    await userEvent.click(summary);
    expect(section).toHaveAttribute("open");
    expect(section).toHaveTextContent("Player 8");
    expect(section).toHaveTextContent("Player 1");
    expect(section).toHaveTextContent("#17");
    expect(section).toHaveTextContent(`${TOP100_COPY[language].legend} 20`);
    // This record's ceiling differs from its price, which only a price measured against
    // an unproven pure-points plan ever did; that figure bounds nothing, so no price.
    expect(section).not.toHaveTextContent(
      TOP100_COPY[language].combinedCostAtMost(language === "tr" ? "4,0" : "4.0"),
    );
    expect(section).not.toHaveTextContent(language === "tr" ? "4,0" : "4.0");
    expect(section).not.toHaveTextContent(language === "tr" ? "2,5" : "2.5");
    const rows = section.querySelectorAll(":scope > ul > li");
    for (const index of [0, 2])
      expect(rows[index]).not.toHaveTextContent(language === "tr" ? "0,0" : "0.0");
  },
);
it.each<Language>(["tr", "en"])(
  "uses the plain price sentence when the recorded ceiling equals the cost in %s",
  async (language) => {
    const value = history();
    Object.assign(value.payload.weeks[0], {
      recorded_plans: [
        { ...planRows[1], expected_points_cost: 4, expected_points_cost_ceiling: 4 },
      ],
    });
    show(value, language);
    await userEvent.selectOptions(screen.getByRole("combobox"), "4");
    await userEvent.click(screen.getByText(MESSAGES[language].suggestionHistory.recordedPlans));
    const price = language === "tr" ? "4,0" : "4.0";
    expect(screen.getByText(TOP100_COPY[language].combinedCost(price))).toBeVisible();
    expect(
      screen.queryByText(TOP100_COPY[language].combinedCostAtMost(price)),
    ).not.toBeInTheDocument();
  },
);
it.each<Language>(["tr", "en"])(
  "prints no price for a priced record that carries no ceiling in %s",
  async (language) => {
    // A ceiling is published only where the plan the price is measured against was
    // proven; a priced record without one was measured against a plan nobody proved.
    const value = history();
    Object.assign(value.payload.weeks[0], {
      recorded_plans: [
        { ...planRows[1], expected_points_cost: 2.5, expected_points_cost_ceiling: undefined },
      ],
    });
    show(value, language);
    await userEvent.selectOptions(screen.getByRole("combobox"), "4");
    await userEvent.click(screen.getByText(MESSAGES[language].suggestionHistory.recordedPlans));
    const price = language === "tr" ? "2,5" : "2.5";
    expect(screen.queryByText(TOP100_COPY[language].combinedCost(price))).not.toBeInTheDocument();
    expect(
      screen.queryByText(TOP100_COPY[language].combinedCostAtMost(price)),
    ).not.toBeInTheDocument();
  },
);
it.each<Language>(["tr", "en"])(
  "prints a scenario-menu mode's recorded price, which never has a ceiling, in %s",
  async (language) => {
    // The scenario menu prices a mode as a difference between two scenario means, not
    // against a solved plan, and publishes no ceiling for it.
    const value = history();
    Object.assign(value.payload.weeks[0], {
      recorded_plans: [
        {
          ...planRows[0],
          published_path: "advice/101/garantici/1.json",
          strategy: "garantici",
          expected_points_cost: 3,
        },
      ],
    });
    show(value, language);
    await userEvent.selectOptions(screen.getByRole("combobox"), "4");
    await userEvent.click(screen.getByText(MESSAGES[language].suggestionHistory.recordedPlans));
    expect(
      screen.getByText(
        MESSAGES[language].leagueMembers.planCost(language === "tr" ? "3,0" : "3.0"),
      ),
    ).toBeVisible();
  },
);
it("does not display negative archived prices", async () => {
  const value = history();
  Object.assign(value.payload.weeks[0], {
    recorded_plans: [
      { ...planRows[1], expected_points_cost: -2, expected_points_cost_ceiling: undefined },
    ],
  });
  show(value, "en");
  await userEvent.selectOptions(screen.getByRole("combobox"), "4");
  await userEvent.click(screen.getByText(MESSAGES.en.suggestionHistory.recordedPlans));
  expect(screen.queryByText(/gives? up/)).not.toBeInTheDocument();
});
const history = () => structuredClone(fixture) as SuggestionHistory;
function show(value = history(), language: Language = "tr", members: EntryView[] = []) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter>
        <LeagueMemberHistoryView history={value} members={members} />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

it.each([true, false])(
  "uses the published rival name with an id fallback (available: %s)",
  async (available) => {
    const rival = mockMembers.find((member) => member.member_kind === "human")!;
    const value = history();
    Object.assign(value.payload.weeks[0], {
      recorded_plans: [{ ...planRows[0], strategy: "ortak-koru", rival_entry_id: rival.entry_id }],
    });
    show(value, "en", available ? [rival] : []);
    await userEvent.selectOptions(screen.getByRole("combobox"), "4");
    const details = screen
      .getByText(MESSAGES.en.suggestionHistory.recordedPlans)
      .closest("details")!;
    await userEvent.click(within(details).getByText(MESSAGES.en.suggestionHistory.recordedPlans));
    expect(details).toHaveTextContent(
      available ? (rival.team_name ?? rival.manager_name)! : `#${rival.entry_id}`,
    );
  },
);

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
    expect(screen.getByText(new RegExp(`${copy.captain} \\(x2\\)`))).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: copy.players })).getAllByRole("columnheader"),
    ).toHaveLength(5);
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
  expect(screen.getByText("Karşılaştırılan hafta: 9/11")).toBeInTheDocument();
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
