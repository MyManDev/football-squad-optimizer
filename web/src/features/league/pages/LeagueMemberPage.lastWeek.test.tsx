/**
 * The card of the member's latest finished week, above this week's decisions: the gameweek,
 * the member's net and how it stands against the league's mean, what the published
 * suggestion scored, the rank movement, the league's mean and the game's average, each from
 * the published scoreboard, the member's squad document or their suggestion history. A
 * finished week nobody has data-checked is marked provisional, as the scoreboard marks it; a
 * figure no file states has no line; and with no week of the member's there is no card. The
 * page reads the scoreboard, and the history only once the scoreboard holds such a week.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import fixture from "../../../fixtures/weeklySuggestionHistory.json";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { memberHistoryAddress } from "../../../lib/leagueAddresses";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { forgetIdentity, stubTree, withLeague } from "../../../testSupport/league";
import { LeagueDataMissing, type LeagueTree } from "../data";
import type { SuggestionHistory } from "../history/historyData";
import type { EntrySquad, LeagueViewEnvelope, Scoreboard, ScoreboardGameweek } from "../types";
import { LeagueMemberPage, LeagueMemberView } from "./LeagueMemberPage";
import type { LeagueMemberViewProps } from "./memberPageTypes";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
beforeEach(() => forgetIdentity());

const ENTRY = 35249001;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;
const MEMBERS = mockLeagueMembersEnvelope.payload.members;
// The example member: GW2 advised, GW1 scored, up two places, rank 1.
const SCORED = SQUAD.payload.scored_gameweek!;

/** One scoreboard week in the published shape, finished and checked unless patched. */
function week(gameweek: number, patch: Partial<ScoreboardGameweek> = {}): ScoreboardGameweek {
  return {
    gameweek,
    deadline_utc: "2026-08-15T17:30:00Z",
    finished: true,
    data_checked: true,
    average_entry_score: 57,
    highest_score: 113,
    ours: null,
    top100: null,
    members: [
      { entry_id: ENTRY, points: 78, hit_cost: 4, net: 74, total_points: 132 },
      { entry_id: 35249002, points: 61, hit_cost: 0, net: 61, total_points: 120 },
    ],
    members_mean_net: 61.4,
    members_counted: 12,
    ...patch,
  };
}

/** The league's scoreboard for the example season: GW1 finished, GW2 still to play. */
function scoreboard(
  weeks: ScoreboardGameweek[] = [
    week(SCORED),
    week(SCORED + 1, {
      finished: false,
      data_checked: false,
      average_entry_score: null,
      highest_score: null,
      members: [],
      members_mean_net: null,
      members_counted: 0,
    }),
  ],
): Scoreboard {
  return {
    season: SQUAD.payload.season,
    league_id: SQUAD.payload.league_id,
    source_snapshot_id: "fpl-live-20260822T040000Z-0123456789ab",
    captured_at_utc: "2026-08-22T04:00:00Z",
    cohort_snapshot_id: null,
    cohort_picks_snapshot_id: null,
    registered_members: 12,
    histories_held: 12,
    gameweeks: weeks,
    cumulative: {
      through_gameweek: SCORED,
      gameweeks: [SCORED],
      ours_net: null,
      ours_gameweeks: [],
      ours_basis: null,
      ours_excluded_gameweeks: [],
      members_mean_total_points: 61.4,
      members_gameweeks: [SCORED],
      members_counted: 12,
      average_entry_score: 57,
    },
  };
}

/**
 * The member's suggestion history with the scored week settled: the fixture's suggestion
 * scored 24 gross less its 4-point hit, 20 net.
 */
function history(): SuggestionHistory {
  const value = structuredClone(fixture) as SuggestionHistory;
  value.payload.entry_id = ENTRY;
  value.payload.weeks[0]!.gameweek = SCORED;
  return value;
}

/** The same week before the publisher could settle it: no score is recorded yet. */
function unsettledHistory(): SuggestionHistory {
  const value = history();
  Object.assign(value.payload.weeks[0]!, {
    status: "unsettled",
    reason: "not_settled",
    suggested: null,
    actual: null,
    net_difference: null,
    players: [],
  });
  return value;
}

function squad(patch: Partial<EntrySquad> = {}): LeagueViewEnvelope<EntrySquad> {
  return { ...SQUAD, payload: { ...SQUAD.payload, ...patch } };
}

function show(language: Language = "tr", props: Partial<LeagueMemberViewProps> = {}) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}`]}>
        {withLeague(
          <LeagueMemberView
            squad={SQUAD}
            advice={mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1)}
            members={MEMBERS}
            index={mockEntryAdviceIndex(ENTRY).payload}
            scoreboard={scoreboard()}
            history={history()}
            {...props}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
}

const card = (container: HTMLElement) => container.querySelector<HTMLElement>("[data-last-week]");
const facts = (container: HTMLElement) =>
  [...card(container)!.querySelectorAll("[data-fact]")].map((cell) =>
    cell.getAttribute("data-fact"),
  );
const fact = (container: HTMLElement, key: string) =>
  card(container)!.querySelector<HTMLElement>(`[data-fact="${key}"]`)!;
const suggestion = (container: HTMLElement) =>
  card(container)!.querySelector<HTMLElement>('[data-line="suggested"]');

describe("the latest finished week's card", () => {
  it.each([
    [
      "tr",
      "Geçen haftanın sonucu",
      "OH1",
      "Lig ortalamasına göre +12,6",
      "2 sıra yükseldi",
      "Önerimiz 20 puan getirdi",
      "En çok puan · 1 hafta",
    ],
    [
      "en",
      "Last week's result",
      "GW1",
      "+12.6 against the league mean",
      "up 2 places",
      "Our suggestion scored 20",
      "Most points · 1 week",
    ],
  ] as const)(
    "says the member's last week with every figure the files state (%s)",
    (language, title, gameweek, against, moved, scored, plan) => {
      const { container } = show(language);
      const copy = MESSAGES[language];
      const shown = card(container)!;
      expect(shown).toHaveAttribute("data-last-week", String(SCORED));
      expect(within(shown).getByRole("heading", { level: 2 })).toHaveTextContent(title);
      expect(shown).toHaveTextContent(gameweek);
      // The member's net from the scoreboard's own row: 78 less the 4-point hit.
      expect(within(shown).getByText("74")).toBeInTheDocument();
      expect(within(shown).getByText(copy.leagueMembers.lastWeekNet)).toBeInTheDocument();
      // 74 against the mean as printed, 61.4: the two figures on the card add up.
      expect(within(shown).getByText(against)).toBeInTheDocument();
      // What the published one-week pure-points suggestion scored that week, named as such.
      expect(within(suggestion(container)!).getByText(scored)).toBeInTheDocument();
      expect(suggestion(container)).toHaveTextContent(plan);
      expect(facts(container)).toEqual(["movement", "mean", "average"]);
      expect(fact(container, "movement")).toHaveTextContent(moved);
      expect(fact(container, "mean")).toHaveTextContent(language === "tr" ? "61,4" : "61.4");
      expect(fact(container, "mean")).toHaveTextContent(copy.leagueMembers.lastWeekMembers(12));
      expect(fact(container, "average")).toHaveTextContent(copy.leagueScoreboard.average);
      expect(fact(container, "average")).toHaveTextContent("57");
      // The recorded expectation stays on the history page, not beside the settled score.
      expect(shown).not.toHaveTextContent(copy.suggestionHistory.expectation);
      // A checked week carries no provisional mark.
      expect(shown).not.toHaveTextContent(copy.leagueScoreboard.provisional);
      expect(
        within(shown).getByRole("link", { name: copy.leagueMembers.lastWeekDetails }),
      ).toHaveAttribute("href", memberHistoryAddress(352490, ENTRY));
      expect(shown.textContent).not.toMatch(AS_A_CHANCE);
      expect(shown.textContent).not.toMatch(AS_A_CAVEAT);
    },
  );

  it("sits above this week's decisions and the decision itself", () => {
    // A solved plan with its captain, so the week's story has a card to show.
    const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    const [captain, vice] = base.payload.starting_xi!;
    const { container } = show("tr", {
      advice: {
        ...base,
        payload: { ...base.payload, solver_status: "OPTIMAL", captain, vice_captain: vice },
      },
    });
    const shown = card(container)!;
    const story = screen.getByRole("navigation", { name: MESSAGES.tr.leagueMembers.storyTitle });
    const decision = screen.getByRole("region", { name: MESSAGES.tr.leagueMembers.decisionTitle });
    expect(shown.compareDocumentPosition(story) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(shown.compareDocumentPosition(decision) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each(["tr", "en"] as const)(
    "marks a finished week nobody has checked yet as provisional (%s)",
    (language) => {
      const copy = MESSAGES[language];
      // The squad document scores only a checked week, so its movement is not this week's.
      const { container } = show(language, {
        squad: squad({ scored_gameweek: null }),
        scoreboard: scoreboard([week(SCORED, { data_checked: false })]),
      });
      const shown = card(container)!;
      expect(within(shown).getByText(copy.leagueScoreboard.provisional)).toBeInTheDocument();
      expect(within(shown).getByText(copy.leagueScoreboard.provisionalNote)).toBeInTheDocument();
      expect(facts(container)).not.toContain("movement");
      expect(within(shown).getByText("74")).toBeInTheDocument();
      // A history from a later capture may have settled the week already; its score sits
      // under the same provisional mark as the rest of the card.
      expect(suggestion(container)).toHaveTextContent(copy.leagueMembers.lastWeekSuggested("20"));
      cleanup();
      // As the publisher writes it, a week not yet checked is unsettled: no score, no line.
      const again = show(language, {
        squad: squad({ scored_gameweek: null }),
        scoreboard: scoreboard([week(SCORED, { data_checked: false })]),
        history: unsettledHistory(),
      });
      expect(
        within(card(again.container)!).getByText(copy.leagueScoreboard.provisional),
      ).toBeInTheDocument();
      expect(suggestion(again.container)).toBeNull();
    },
  );

  it.each(["tr", "en"] as const)("leaves out each line no file states (%s)", (language) => {
    const copy = MESSAGES[language];
    const unknown = {
      ...SQUAD.payload.entry,
      movement: "unknown" as const,
      movement_places: null,
    };
    const { container } = show(language, {
      squad: squad({ entry: unknown }),
      scoreboard: scoreboard([week(SCORED, { members_mean_net: null, average_entry_score: null })]),
      history: null,
    });
    const shown = card(container)!;
    expect(within(shown).getByText("74")).toBeInTheDocument();
    expect(facts(container)).toEqual([]);
    expect(shown.querySelector("dl")).toBeNull();
    expect(shown.textContent).not.toContain(copy.leagueMembers.lastWeekAgainstMean("").trim());
    expect(within(shown).queryByRole("link")).toBeNull();
    expect(suggestion(container)).toBeNull();
    // No zero stands in for an absent figure.
    expect(shown.textContent).not.toMatch(/\b0([.,]0)?\b/);
  });

  it.each(["tr", "en"] as const)(
    "says the suggestion's score only for a week the history settled (%s)",
    (language) => {
      const unsettled = show(language, { history: unsettledHistory() });
      expect(suggestion(unsettled.container)).toBeNull();
      expect(within(card(unsettled.container)!).queryByRole("link")).toBeNull();
      cleanup();
      // An available week whose score is not stated is no score either.
      const unscored = history();
      unscored.payload.weeks[0]!.suggested = null;
      expect(suggestion(show(language, { history: unscored }).container)).toBeNull();
      cleanup();
      // Another member's history, or another week's, says nothing about this one.
      const other = history();
      other.payload.entry_id = 35249002;
      expect(suggestion(show(language, { history: other }).container)).toBeNull();
      cleanup();
      const later = history();
      later.payload.weeks[0]!.gameweek = SCORED + 1;
      expect(suggestion(show(language, { history: later }).container)).toBeNull();
    },
  );

  it("writes a week below the league's mean with its minus sign", () => {
    const { container } = show("en", {
      scoreboard: scoreboard([week(SCORED, { members_mean_net: 77.04 })]),
    });
    expect(within(card(container)!).getByText("−3.0 against the league mean")).toBeInTheDocument();
  });

  it("names a finished week that is not the one before the advised week by itself", () => {
    const { container } = show("tr", { squad: squad({ gameweek: SCORED + 2 }) });
    const shown = card(container)!;
    expect(within(shown).getByRole("heading", { level: 2 })).toHaveTextContent(
      MESSAGES.tr.leagueMembers.latestWeekTitle,
    );
    expect(shown).toHaveTextContent("OH1");
  });

  it.each<[string, Partial<LeagueMemberViewProps>]>([
    ["no scoreboard", { scoreboard: null }],
    ["no finished week", { scoreboard: scoreboard([week(SCORED, { finished: false })]) }],
    ["another season's scoreboard", { scoreboard: { ...scoreboard(), season: "2025-26" } }],
    ["another league's scoreboard", { scoreboard: { ...scoreboard(), league_id: 1 } }],
    [
      "no row for the member",
      { scoreboard: scoreboard([week(SCORED, { members: week(SCORED).members.slice(1) })]) },
    ],
    [
      "a row whose hit is unknown",
      {
        scoreboard: scoreboard([
          week(SCORED, {
            members: [
              { entry_id: ENTRY, points: 78, hit_cost: null, net: null, total_points: 132 },
            ],
          }),
        ]),
      },
    ],
  ])("shows no card with %s", (_, props) => {
    const { container } = show("tr", props);
    expect(card(container)).toBeNull();
    expect(screen.queryByText(MESSAGES.tr.leagueMembers.lastWeekTitle)).toBeNull();
  });

  it("comes in once, in the motion tokens' data time", () => {
    const css = readFileSync(join(__dirname, "LastWeekCard.module.css"), "utf-8").replace(
      /\/\*[\s\S]*?\*\//g,
      "",
    );
    const rule = css.match(/\.enter\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(rule).toMatch(/animation:\s*last-week-in var\(--motion-data\) var\(--motion-ease\);/);
    // Finite: one run, no repeat, and the global reduced-motion rule stops it.
    expect(css).not.toMatch(/infinite|animation-iteration-count/);
    expect(css).toMatch(/@keyframes last-week-in\s*\{\s*from\s*\{\s*opacity:\s*0;/);
  });
});

describe("the card's reads", () => {
  function page(board: Scoreboard | Error, member: SuggestionHistory | Error = history()) {
    const raw = vi.fn<LeagueTree["raw"]>().mockImplementation(async (relative) => {
      if (relative !== `history/${ENTRY}.json`) throw new LeagueDataMissing(relative);
      if (member instanceof Error) throw member;
      return member;
    });
    stubTree({
      members: vi.fn<LeagueTree["members"]>().mockResolvedValue(mockLeagueMembersEnvelope),
      entrySquad: vi.fn<LeagueTree["entrySquad"]>().mockResolvedValue(SQUAD),
      entryAdviceIndex: vi
        .fn<LeagueTree["entryAdviceIndex"]>()
        .mockResolvedValue(mockEntryAdviceIndex(ENTRY)),
      entryAdvice: vi
        .fn<LeagueTree["entryAdvice"]>()
        .mockResolvedValue(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1)),
      scoreboard: vi.fn<LeagueTree["scoreboard"]>().mockImplementation(async () => {
        if (board instanceof Error) throw board;
        return {
          contract_version: "provisional_league_ui_v1",
          generated_at_utc: "2026-08-22T04:10:00Z",
          source_kind: "live",
          payload: board,
        };
      }),
      raw,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("", { status: 404 })),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <LanguageProvider initialLanguage="tr">
          <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}`]}>
            {withLeague(
              <Routes>
                <Route path="/league/:leagueId/members/:entryId" element={<LeagueMemberPage />} />
              </Routes>,
            )}
          </MemoryRouter>
        </LanguageProvider>
      </QueryClientProvider>,
    );
    return { container, raw };
  }

  afterEach(() => vi.unstubAllGlobals());

  const historyReads = (raw: Mock<LeagueTree["raw"]>) =>
    raw.mock.calls.filter(([relative]) => relative === `history/${ENTRY}.json`);

  it("reads the scoreboard, then the member's history for the suggestion's score", async () => {
    const { container, raw } = page(scoreboard());
    await waitFor(() => expect(card(container)).not.toBeNull());
    await waitFor(() =>
      expect(suggestion(container)).toHaveTextContent(
        MESSAGES.tr.leagueMembers.lastWeekSuggested("20"),
      ),
    );
    expect(historyReads(raw)).toHaveLength(1);
  });

  it("reads no history while the scoreboard holds no week of the member's", async () => {
    const { container, raw } = page(
      scoreboard([week(SCORED, { members: week(SCORED).members.slice(1) })]),
    );
    await screen.findByRole("region", { name: MESSAGES.tr.leagueMembers.decisionTitle });
    expect(card(container)).toBeNull();
    expect(historyReads(raw)).toHaveLength(0);
  });

  it("keeps the page and leaves the card out when the scoreboard cannot be read", async () => {
    const { container } = page(new Error("broken"));
    expect(
      await screen.findByRole("region", { name: MESSAGES.tr.leagueMembers.decisionTitle }),
    ).toBeInTheDocument();
    expect(card(container)).toBeNull();
  });

  it("keeps the card without the suggestion's score when the history is not published", async () => {
    const { container, raw } = page(scoreboard(), new LeagueDataMissing(`history/${ENTRY}.json`));
    await waitFor(() => expect(card(container)).not.toBeNull());
    await waitFor(() => expect(historyReads(raw)).toHaveLength(1));
    expect(facts(container)).toEqual(["movement", "mean", "average"]);
    expect(suggestion(container)).toBeNull();
    expect(within(card(container)!).queryByRole("link")).toBeNull();
  });
});
