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
import { withLeague } from "../../../testSupport/league";

afterEach(cleanup);
it.each<Language>(["tr", "en"])("labels requested weeks concisely in %s", async (language) => {
  const value = history();
  Object.assign(value.payload.weeks[0], {
    advice_source: "requested_server",
    request_cache_key: "a".repeat(64),
  });
  show(value, language);
  const copy = MESSAGES[language].suggestionHistory;
  expect(screen.getByText(copy.requested)).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByRole("combobox"), "4");
  expect(screen.getByText(copy.requested)).toBeInTheDocument();
  expect(screen.getByText(`${copy.difference}:`).textContent).toMatch(/−2[,.]0/);
});
it.each<Language>(["tr", "en"])(
  "keeps only the plain plan, collapsed and without a price, in %s",
  async (language) => {
    const value = history();
    Object.assign(value.payload.weeks[0], { recorded_plans: planRows });
    show(value, language);
    const { suggestionHistory: copy, leagueMembers, decision } = MESSAGES[language];
    await userEvent.selectOptions(screen.getByRole("combobox"), "4");
    const summary = screen.getByText(copy.recordedPlans);
    const section = summary.closest("details")!;
    expect(section).not.toHaveAttribute("open");
    await userEvent.click(summary);
    expect(section).toHaveAttribute("open");
    expect(section).toHaveTextContent(
      `${leagueMembers.strategies["saf-puan"].name}, ${decision.week(1)}`,
    );
    expect(section).toHaveTextContent(`${copy.captain}: Player 8`);
    expect(section).toHaveTextContent(copy.noRecordedMoves);
    // The fixture's other two rows are the same week's plans under a setting and a chip.
    expect(section).not.toHaveTextContent("Player 1");
    expect(section).not.toHaveTextContent("#17");
    expect(section).not.toHaveTextContent("Top 100");
    expect(section).not.toHaveTextContent(leagueMembers.chipNames.bboost);
    expect(section).not.toHaveTextContent(/gives? up|vazgeç/);
  },
);
it("lists the plain plan's moves by name and leaves out a move the record cannot name", async () => {
  const value = history();
  Object.assign(value.payload.weeks[0], {
    recorded_plans: [
      {
        ...planRows[0],
        moves: [
          { player_out: "Player 1", player_in: "Player 17" },
          { player_out: "Player 2", player_in: null },
        ],
      },
    ],
  });
  show(value, "en");
  await userEvent.selectOptions(screen.getByRole("combobox"), "4");
  const summary = screen.getByText(MESSAGES.en.suggestionHistory.recordedPlans);
  await userEvent.click(summary);
  expect(
    within(summary.closest("details")!)
      .getAllByRole("listitem")
      .map((move) => move.textContent),
  ).toEqual(["Out: Player 1; In: Player 17"]);
});
it("does not say a plan has no moves when its only moves cannot be named", async () => {
  const value = history();
  Object.assign(value.payload.weeks[0], {
    recorded_plans: [{ ...planRows[0], moves: [{ player_out: null, player_in: null }] }],
  });
  show(value, "en");
  await userEvent.selectOptions(screen.getByRole("combobox"), "4");
  const copy = MESSAGES.en.suggestionHistory;
  const summary = screen.getByText(copy.recordedPlans);
  await userEvent.click(summary);
  const section = summary.closest("details")!;
  expect(within(section).queryByRole("list")).not.toBeInTheDocument();
  expect(section).not.toHaveTextContent(copy.noRecordedMoves);
});
it("leaves no plan card when no recorded plan is the plain one", async () => {
  const value = history();
  Object.assign(value.payload.weeks[0], {
    recorded_plans: [
      planRows[1],
      planRows[2],
      { ...planRows[0], strategy: "ortak-koru", rival_entry_id: 202 },
    ],
  });
  show(value);
  await userEvent.selectOptions(screen.getByRole("combobox"), "4");
  expect(screen.queryByText(MESSAGES.tr.suggestionHistory.recordedPlans)).not.toBeInTheDocument();
});
const history = () => structuredClone(fixture) as SuggestionHistory;
function show(value = history(), language: Language = "tr") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter>{withLeague(<LeagueMemberHistoryView history={value} />)}</MemoryRouter>
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
    expect(
      within(screen.getByRole("region", { name: copy.players })).getAllByRole("row"),
    ).toHaveLength(16);
    expect(screen.getByText(new RegExp(`${copy.captain} \\(x2\\)`))).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: copy.players }))
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual([copy.player, copy.role, copy.realized]);
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

it.each<Language>(["tr", "en"])(
  "names a week it cannot compare only when that week is selected in %s",
  async (language) => {
    const value = history();
    value.payload.weeks.unshift({
      ...value.payload.weeks[0],
      gameweek: 5,
      status: "unavailable",
      reason: "not_published",
      advice_snapshot_id: null,
      advice_captured_at_utc: null,
      advice_generated_at_utc: null,
      advice_sha256: null,
      outcome_snapshot_id: null,
      outcome_captured_at_utc: null,
      expected_own_points: null,
      suggested: null,
      actual: null,
      actual_reason: null,
      net_difference: null,
      players: [],
    });
    show(value, language);
    const copy = MESSAGES[language].suggestionHistory;
    expect(screen.queryByText(copy.unavailable)).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: copy.week }), "5");
    expect(screen.getByText(copy.unavailable)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  },
);

it("opens all recorded weeks by default, shows totals, and returns from a selected week", async () => {
  show(mockSuggestionOverview());
  const overview = screen.getByRole("region", { name: "Genel bakış" });
  expect(within(overview).getAllByRole("row")).toHaveLength(13);
  expect(
    within(within(overview).getByRole("row", { name: /^Toplam/ }))
      .getAllByRole("cell")
      .map((cell) => cell.textContent),
  ).toEqual(["624,0", "610,0", "+14,0", "+14,0"]);
  expect(within(overview).getByText("Sonuç kesinleşmedi")).toBeInTheDocument();
  // A week's name starts with what the button prints, so a voice command for it finds it.
  for (const button of within(overview).getAllByRole("button")) {
    expect(button).toHaveAccessibleName(expect.stringMatching(/^OH\d+, Oyun haftası \d+$/));
    expect(button.getAttribute("aria-label")!.startsWith(button.textContent!)).toBe(true);
  }
  await userEvent.click(within(overview).getByRole("button", { name: "OH5, Oyun haftası 5" }));
  expect(screen.getByRole("combobox")).toHaveValue("5");
  expect(screen.queryByRole("region", { name: "Genel bakış" })).not.toBeInTheDocument();
  expect(screen.getByText("Fark:")).toHaveTextContent("+6,0");
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
