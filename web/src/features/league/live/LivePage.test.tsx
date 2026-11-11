/**
 * LIVE's reads and what they draw, with the forwarder and the table injected: the page opens
 * with one read of each document, Yenile reads the live document alone, an older copy and a
 * read that is not answered keep the board shown, the week is the bundle's current week
 * however far the published squad has moved on, a team on its own has no rival, and a
 * head-to-head league sets the live week's opponent beside the member.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { PHONE_QUERY } from "../../../design/shell/layout";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { claimIn, forgetIdentity } from "../../../testSupport/league";
import {
  testActivity,
  testFixtures,
  testPicks,
  testWeek,
  TEST_WEEK,
} from "../../../testSupport/liveWeek";
import { FIXTURES_QUERY } from "../../fixtures/data";
import type { WeekActivity } from "../../liveScore/weekActivity";
import type { MemberWeek } from "../../liveScore/weekLive";
import type { LeagueTree } from "../data";
import { leagueKeys } from "../queries";
import type { PublishedLeague } from "../directory";
import { ForwardedLeagueContext, type ForwardedLeague } from "../forwarded/ForwardedLeagueContext";
import type { ForwarderResult, LiveReason } from "../forwarder/client";
import type { FplEntryBundle, FplH2hMatches } from "../forwarder/documents";
import { LeagueContext } from "../LeagueContext";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { LivePage } from "./LivePage";
import { signedWhole } from "./liveFormat";
import type { LiveForwarder } from "./liveSources";
import { WIDE_QUERY } from "./useWide";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  sessionStorage.clear();
  forgetIdentity();
  delete (window as { matchMedia?: unknown }).matchMedia;
});

/** The screen as media queries answer it: `matching` holds and no other query does. */
function screenWhere(matching: string) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      media: query,
      matches: query === matching,
      addEventListener() {},
      removeEventListener() {},
    }),
  });
}

const copy = MESSAGES.tr;
const ENTRY = 35249001;
const RIVAL = 35249002;
const LEAGUE: PublishedLeague = {
  leagueId: 352490,
  leagueName: "SquadOpt Classic League",
  season: "2026-27",
  gameweek: TEST_WEEK,
  path: "league",
};

const week = testWeek({
  picks: testPicks().map((pick) => (pick.id === 4 ? { ...pick, points: 3, minutes: 40 } : pick)),
});

function squad(gameweek: number, leagueId = LEAGUE.leagueId): LeagueViewEnvelope<EntrySquad> {
  const envelope = mockEntrySquadEnvelopes[ENTRY]!;
  return {
    ...envelope,
    payload: {
      ...envelope.payload,
      league_id: leagueId,
      season: "2026-27",
      gameweek,
      source_snapshot_id: week.table.source_snapshot_id,
    },
  };
}

const bundle = (entryId: number, current: MemberWeek): FplEntryBundle => ({
  contract_version: "fpl_entry_bundle_v1",
  entry_id: entryId,
  gameweek: current.gameweek,
  source_time: "2026-11-21T15:00:00Z",
  entry: { id: entryId, name: "Synthetic XI", started_event: 1 },
  history: { current: [], chips: [] },
  transfers: [],
  picks: [],
  current_week: current,
});

/** The live document at `sourceTime`, Player 4 with `points` and `goals`. */
function live(sourceTime: string, points = 3, goals = 0): WeekActivity {
  const input = testWeek({
    sourceTime,
    picks: testPicks().map((pick) => (pick.id === 4 ? { ...pick, points, minutes: 40 } : pick)),
  });
  return {
    contract_version: "week_activity_v1",
    week: input.live,
    activity: testActivity(input, { inPlay: [102], goals: { 4: goals } }),
  };
}

/** The live document at `sourceTime`: Players 4 and 8, both picked by the member and the rival, score. */
function liveTwoGoals(sourceTime: string): WeekActivity {
  const input = testWeek({
    sourceTime,
    picks: testPicks().map((pick) =>
      pick.id === 4
        ? { ...pick, points: 9, minutes: 40 }
        : pick.id === 8
          ? { ...pick, points: 6, minutes: 40 }
          : pick,
    ),
  });
  return {
    contract_version: "week_activity_v1",
    week: input.live,
    activity: testActivity(input, { inPlay: [102], goals: { 4: 1, 8: 1 } }),
  };
}

type LiveAnswer = ForwarderResult<WeekActivity, LiveReason>;
const answered = (document: WeekActivity): LiveAnswer => ({ ok: true, copy: null, document });

function fakeForwarder(answers: LiveAnswer[], { opponent }: { opponent?: number } = {}) {
  let reads = 0;
  const forwarder = {
    entryBundle: vi.fn(async (entryId: number) => ({
      ok: true as const,
      copy: null,
      document: bundle(
        entryId,
        entryId === ENTRY
          ? week.member
          : { ...week.member, entry_id: entryId, captain: 7, vice: 10 },
      ),
    })),
    liveActivity: vi.fn(async () => answers[Math.min(reads++, answers.length - 1)]!),
    liveWeek: vi.fn(async () => ({ ok: false as const, reason: "not_found" as const })),
    h2hMatches: vi.fn(
      async (league: number, gameweek: number, page: number) =>
        ({
          ok: true,
          copy: null,
          document: {
            contract_version: "fpl_h2h_matches_v1",
            league: { id: league, scoring: "h2h" },
            gameweek,
            page,
            has_next: false,
            source_time: "2026-11-21T15:00:00Z",
            results: [
              {
                id: 1,
                entry_1: { entry: ENTRY, name: "North Stand Notes", player_name: "x", points: 0 },
                entry_2: {
                  entry: gameweek === TEST_WEEK ? (opponent ?? null) : RIVAL,
                  name: "Paired",
                  player_name: "y",
                  points: 0,
                },
                winner: null,
                started: true,
                finished: false,
              },
            ],
          },
        }) satisfies ForwarderResult<FplH2hMatches, never>,
    ),
  } satisfies LiveForwarder;
  return forwarder;
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

/**
 * The league's members document, scored through `gameweek`: North Stand Notes on 132 in all
 * (74 that week), Half Space on 127 (68 that week).
 */
const membersScored = (gameweek: number | null) => ({
  ...mockLeagueMembersEnvelope,
  payload: { ...mockLeagueMembersEnvelope.payload, scored_gameweek: gameweek },
});

/** Toplam fark as the duel shows it, or null where it shows none. */
function shownGap(): string | null {
  return screen.queryByText(copy.live.totalGap)?.nextElementSibling?.textContent ?? null;
}

/** A figure the page shows, as a number. */
const figure = (text: string | null | undefined) => Number((text ?? "").replace("−", "-"));

function renderLive({
  forwarder,
  path = `/league/${LEAGUE.leagueId}/members/${ENTRY}/live`,
  page = squad(TEST_WEEK),
  league = LEAGUE,
  forwardedLeague = null,
  members = membersScored(TEST_WEEK - 1),
  language = "tr",
  heldSquad = false,
  calendar = week.fixtures,
}: {
  forwarder: LiveForwarder;
  path?: string;
  page?: LeagueViewEnvelope<EntrySquad>;
  league?: PublishedLeague;
  forwardedLeague?: ForwardedLeague | null;
  members?: ReturnType<typeof membersScored>;
  language?: "tr" | "en";
  /** The squad is held from ten minutes ago, and the read of it again fails. */
  heldSquad?: boolean;
  calendar?: typeof week.fixtures;
}) {
  const loadTable = vi.fn(async () => ({
    contract_version: "provisional_league_ui_v1" as const,
    generated_at_utc: "2026-11-20T09:00:00Z",
    source_kind: "live" as const,
    payload: week.table,
  }));
  const tree = {
    league,
    entrySquad: vi.fn(async () => {
      if (heldSquad) throw new Error("The squad could not be read.");
      return page;
    }),
    members: vi.fn(async () => members),
    entryAdviceIndex: vi.fn(async (entryId: number) => mockEntryAdviceIndex(entryId)),
  } as unknown as LeagueTree;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(FIXTURES_QUERY.queryKey, calendar);
  if (heldSquad) {
    const key = leagueKeys.entrySquad(league.leagueId, page.payload.entry.entry_id);
    client.setQueryData(key, page, { updatedAt: Date.now() - 10 * 60_000 });
  }
  const element = <LivePage dependencies={{ forwarder, loadTable }} />;
  const user = userEvent.setup(
    vi.isFakeTimers() ? { advanceTimers: vi.advanceTimersByTime.bind(vi) } : {},
  );
  render(
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[path]}>
          <ForwardedLeagueContext.Provider value={forwardedLeague}>
            <LeagueContext.Provider
              value={{
                league,
                tree,
                ...(forwardedLeague !== null || league.leagueId === 0
                  ? { forwarded: true as const }
                  : {}),
              }}
            >
              <Routes>
                <Route path="/league/:leagueId/members/:entryId/live" element={element} />
                <Route path="/entry/:entryId/live" element={element} />
              </Routes>
            </LeagueContext.Provider>
          </ForwardedLeagueContext.Provider>
          <LocationProbe />
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
  return { user, loadTable, tree };
}

const rows = () =>
  screen.findAllByRole("listitem", { name: /, (Oynuyor|Oynayacak|Bitti|Yedekler)/ });
const net = () => document.querySelector("[data-live-total]")?.textContent;
const recapRegion = () => screen.queryByRole("region", { name: copy.live.sinceLastLook });

/** The GOL board raised for `kind`, once it is up. */
const raised = (kind: "goal" | "assist") =>
  vi.waitFor(() => {
    const board = document.querySelector<HTMLElement>(`[data-goal-board='${kind}']`);
    expect(board).not.toBeNull();
    return board!;
  });

describe("the LIVE page's reads", () => {
  it("opens with one read of each document and the week the bundle names", async () => {
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))]);
    const { loadTable } = renderLive({ forwarder });
    expect(await rows()).toHaveLength(15);
    expect(screen.getByRole("heading", { level: 1, name: copy.live.title })).toBeInTheDocument();
    expect(
      screen.getByText(`North Stand Notes · ${copy.suggestionHistory.gameweek(TEST_WEEK)}`),
    ).toBeInTheDocument();
    await screen.findByText(copy.live.totalGap);
    // The league's totals after the week before, 132 and 127, each with its live net.
    const net = figure(document.querySelector("[data-live-total]")?.textContent);
    const rivalNet = figure(document.querySelector("[data-live-rival-net]")?.textContent);
    expect(shownGap()).toBe(signedWhole(132 + net - (127 + rivalNet), "tr-TR"));
    expect(forwarder.entryBundle.mock.calls.map(([entryId]) => entryId).sort()).toEqual([
      ENTRY,
      RIVAL,
    ]);
    expect(forwarder.liveActivity).toHaveBeenCalledTimes(1);
    expect(loadTable).toHaveBeenCalledTimes(1);
    expect(forwarder.h2hMatches).not.toHaveBeenCalled();
    // Labels and values only.
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(AS_A_CHANCE);
    expect(text).not.toMatch(AS_A_CAVEAT);
  });

  it("reads the live document alone on Yenile, keeps a newer board over an older copy, and says what changed", async () => {
    const forwarder = fakeForwarder([
      answered(live("2026-11-21T15:30:00Z", 3)),
      answered(live("2026-11-21T15:20:00Z", 9)),
      answered(live("2026-11-21T15:31:00Z", 9, 1)),
    ]);
    const { user } = renderLive({ forwarder });
    await rows();
    // The first read is a starting point: no board.
    expect(document.querySelector("[data-goal-board]")).toBeNull();
    const before = net();
    const refresh = screen.getByRole("button", { name: copy.live.refresh });
    await user.click(refresh);
    await vi.waitFor(() => expect(forwarder.liveActivity).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("button", { name: copy.live.refresh })).not.toHaveAttribute(
      "aria-disabled",
    );
    // The older copy changes nothing.
    expect(net()).toBe(before);
    expect(recapRegion()).toBeNull();
    expect(document.querySelector("[data-goal-board]")).toBeNull();
    await user.click(screen.getByRole("button", { name: copy.live.refresh }));
    // The newer read raises the board for P4's goal; what it changed is told once it lands.
    const board = await raised("goal");
    expect(board).toHaveTextContent("P4");
    expect(net()).toBe(before);
    expect(recapRegion()).toBeNull();
    fireEvent.click(board);
    const recap = await screen.findByRole("region", { name: copy.live.sinceLastLook });
    expect(within(recap).getByRole("listitem")).toHaveAccessibleName("P4, Gol 1, +6");
    expect(net()).not.toBe(before);
    expect(forwarder.liveActivity).toHaveBeenCalledTimes(3);
    expect(forwarder.entryBundle).toHaveBeenCalledTimes(2);
  });

  it("keeps the board and its time when a refresh is not answered", async () => {
    const forwarder = fakeForwarder([
      answered(live("2026-11-21T15:30:00Z")),
      { ok: false, reason: "upstream_unavailable" },
    ]);
    const { user } = renderLive({ forwarder });
    await rows();
    const time = screen.getByText(copy.live.updated).querySelector("time")?.dateTime;
    await user.click(screen.getByRole("button", { name: copy.live.refresh }));
    await vi.waitFor(() => expect(forwarder.liveActivity).toHaveBeenCalledTimes(2));
    expect(await rows()).toHaveLength(15);
    expect(screen.getByText(copy.live.updated).querySelector("time")?.dateTime).toBe(time);
  });

  it("keeps drawing the squad it holds when a later read of it fails", async () => {
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))]);
    const { tree } = renderLive({ forwarder, heldSquad: true });
    await vi.waitFor(() => expect(tree.entrySquad).toHaveBeenCalledTimes(1));
    expect(await rows()).toHaveLength(15);
    expect(screen.queryByText(copy.leagueMembers.toolEmpty)).toBeNull();
  });

  it("says there is nothing here when the first read is not answered", async () => {
    const forwarder = fakeForwarder([{ ok: false, reason: "upstream_unavailable" }]);
    renderLive({ forwarder });
    expect(await screen.findByText(copy.leagueMembers.toolEmpty)).toBeInTheDocument();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("reads nothing more by itself between weeks", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-23T10:00:00Z"));
    const forwarder = fakeForwarder([answered(live("2026-11-21T19:30:00Z"))]);
    renderLive({ forwarder });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30 * 60_000);
    });
    expect(forwarder.liveActivity).toHaveBeenCalledTimes(1);
  });

  it("follows the live week once a minute while one of the member's matches is played", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-21T15:30:00Z"));
    const forwarder = fakeForwarder([
      answered(live("2026-11-21T15:29:00Z")),
      answered(live("2026-11-21T15:30:00Z", 9, 1)),
    ]);
    renderLive({ forwarder });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    expect(forwarder.liveActivity).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("img", { name: copy.live.matchInProgress })).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    await vi.waitFor(() => expect(forwarder.liveActivity).toHaveBeenCalledTimes(2));
    // The followed read is the live document alone, scored for both sides.
    expect(forwarder.entryBundle).toHaveBeenCalledTimes(2);
    // Its goal raises the board, and the recap tells it once the board lands.
    const board = await raised("goal");
    expect(board).toHaveTextContent("P4");
    expect(recapRegion()).toBeNull();
    fireEvent.click(board);
    await vi.waitFor(() => expect(recapRegion()).toBeInTheDocument());
  });

  it("puts the heading's light out at the bound that ends the member's match, though FPL has not finished it", async () => {
    // The 15:00 match, two hours and sixteen minutes on: FPL still has it unfinished.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-21T17:16:00Z"));
    const forwarder = fakeForwarder([answered(live("2026-11-21T17:16:00Z"))]);
    renderLive({ forwarder });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    // Its rows are in Bitti, and nothing of the member's is being played.
    expect(screen.queryByRole("heading", { name: copy.live.groups.playing })).toBeNull();
    expect(screen.getByRole("listitem", { name: /^P4, / })).toHaveAccessibleName(
      expect.stringContaining(copy.live.groups.finished),
    );
    // The reads still follow the match FPL has not finished, but the light is out.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    await vi.waitFor(() => expect(forwarder.liveActivity).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("img", { name: copy.live.matchInProgress })).toBeNull();
  });

  it("reads nothing more by itself while only other clubs play", async () => {
    // The member's three matches are over; clubs 7 and 8, none of the member's, kicked off
    // half an hour ago.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-21T20:00:00Z"));
    const fixtures = [
      ...testFixtures().map((fixture) => ({ ...fixture, finished: true })),
      { id: 104, home: 7, away: 8, kickoff: "2026-11-21T19:30:00Z", finished: false },
    ];
    const input = testWeek({ sourceTime: "2026-11-21T20:00:00Z", fixtures });
    const forwarder = fakeForwarder([
      answered({
        contract_version: "week_activity_v1",
        week: input.live,
        activity: testActivity(input, { inPlay: [104] }),
      }),
    ]);
    renderLive({ forwarder, calendar: input.fixtures });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3 * 60_000);
    });
    expect(forwarder.liveActivity).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("img", { name: copy.live.matchInProgress })).toBeNull();
  });

  it("holds what changed through a quiet followed read, until the visitor looks again", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-21T15:30:00Z"));
    const forwarder = fakeForwarder([
      answered(live("2026-11-21T15:29:00Z")),
      answered(live("2026-11-21T15:30:00Z", 9, 1)),
      answered(live("2026-11-21T15:31:00Z", 9, 1)),
      answered(live("2026-11-21T15:32:00Z", 9, 1)),
    ]);
    const { user } = renderLive({ forwarder });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    for (const reads of [2, 3]) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      await vi.waitFor(() => expect(forwarder.liveActivity).toHaveBeenCalledTimes(reads));
      // The goal's read raises the board; the quiet read after it raises none.
      if (reads === 2) fireEvent.click(await raised("goal"));
    }
    expect(document.querySelector("[data-goal-board]")).toBeNull();
    // The goal stays told after the read that brought nothing.
    await vi.waitFor(() =>
      expect(within(recapRegion()!).getByRole("listitem")).toHaveAccessibleName("P4, Gol 1, +6"),
    );
    // Yenile is the visitor looking: what was told goes, and the quiet read tells nothing.
    await user.click(screen.getByRole("button", { name: copy.live.refresh }));
    await vi.waitFor(() => expect(forwarder.liveActivity).toHaveBeenCalledTimes(4));
    await vi.waitFor(() => expect(recapRegion()).toBeNull());
  });
});

describe("the GOL board on LIVE", () => {
  it("rises for the member's goal, and Canlı puan takes its points when they land", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-21T15:30:00Z"));
    const forwarder = fakeForwarder([
      answered(live("2026-11-21T15:29:00Z")),
      answered(live("2026-11-21T15:30:00Z", 9, 1)),
    ]);
    renderLive({ forwarder });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    // The first read is a starting point: no board.
    expect(document.querySelector("[data-goal-board]")).toBeNull();
    const before = Number(net());
    const scorer = () => document.querySelector("[data-live-row='4']")!;
    const duel = () => document.querySelector("[data-live-rival]")!;
    await vi.waitFor(() => expect(duel()).toHaveTextContent(`North Stand Notes ${before}`));
    expect(scorer()).toHaveAccessibleName(expect.stringContaining(copy.live.points("3")));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    const board = await raised("goal");
    expect(board).toHaveTextContent("P4");
    // The defender's six points wait on the board: Canlı puan, the duel, the rows and the
    // recap stand as the read before left them.
    expect(Number(net())).toBe(before);
    expect(duel()).toHaveTextContent(`North Stand Notes ${before}`);
    expect(scorer()).toHaveAccessibleName(expect.stringContaining(copy.live.points("3")));
    expect(recapRegion()).toBeNull();
    fireEvent.click(board);
    await vi.waitFor(() => expect(Number(net())).toBe(before + 6));
    expect(duel()).toHaveTextContent(`North Stand Notes ${before + 6}`);
    expect(scorer()).toHaveAccessibleName(expect.stringContaining(copy.live.points("9")));
    expect(scorer()).toHaveAccessibleName(expect.stringContaining(`${copy.live.goal} 1`));
    expect(within(recapRegion()!).getByRole("listitem")).toHaveAccessibleName("P4, Gol 1, +6");
  });

  it("keeps the rival's points and the duel as the read before left them while the board waits", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-21T15:30:00Z"));
    const forwarder = fakeForwarder([
      answered(live("2026-11-21T15:29:00Z")),
      answered(live("2026-11-21T15:30:00Z", 9, 1)),
    ]);
    renderLive({ forwarder });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    const rivalNet = () => Number(document.querySelector("[data-live-rival-net]")?.textContent);
    const status = () => document.querySelector("[data-live-rival] p")?.textContent;
    await vi.waitFor(() => expect(rivalNet()).toBeGreaterThan(0));
    const before = { rival: rivalNet(), status: status() };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    const board = await raised("goal");
    // The rival fields the scorer too: the read brings both sides his six, and the rival's
    // side and the duel wait for the board as the member's own points do.
    expect(rivalNet()).toBe(before.rival);
    expect(status()).toBe(before.status);
    fireEvent.click(board);
    await vi.waitFor(() => expect(rivalNet()).toBe(before.rival + 6));
  });

  it("keeps the whole duel on the read before between the landings of a read's two goals", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-21T15:30:00Z"));
    const forwarder = fakeForwarder([
      answered(live("2026-11-21T15:29:00Z")),
      answered(liveTwoGoals("2026-11-21T15:30:00Z")),
    ]);
    renderLive({ forwarder });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    const rivalNet = () => Number(document.querySelector("[data-live-rival-net]")?.textContent);
    const status = () => document.querySelector("[data-live-rival] p")?.textContent;
    await vi.waitFor(() => expect(rivalNet()).toBeGreaterThan(0));
    const before = { net: Number(net()), rival: rivalNet(), status: status() };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    fireEvent.click(await raised("goal"));
    // The first goal has landed in Canlı puan; the duel, its ends and the rival wait for the second.
    await vi.waitFor(() => expect(Number(net())).toBeGreaterThan(before.net));
    expect(rivalNet()).toBe(before.rival);
    expect(status()).toBe(before.status);
    expect(document.querySelector("[data-live-rival]")).toHaveTextContent(
      `North Stand Notes ${before.net}`,
    );
    fireEvent.click(await raised("goal"));
    // Both sides field both scorers: the duel takes the read whole, its Fark where it was.
    await vi.waitFor(() => expect(rivalNet()).toBeGreaterThan(before.rival));
    expect(status()).toBe(before.status);
  });

  it("keeps a rival picked while the board plays out of sight until the board has played", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-21T15:30:00Z"));
    const forwarder = fakeForwarder([
      answered(live("2026-11-21T15:29:00Z")),
      answered(live("2026-11-21T15:30:00Z", 9, 1)),
    ]);
    const { user } = renderLive({ forwarder });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    await vi.waitFor(() => expect(document.querySelector("[data-live-rival-net]")).not.toBeNull());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    const board = await raised("goal");
    await user.selectOptions(screen.getByRole("combobox", { name: copy.live.rival }), "35249005");
    await vi.waitFor(() =>
      expect(forwarder.entryBundle.mock.calls.map(([entryId]) => entryId)).toContain(35249005),
    );
    // The new rival's duel would mix the read before with the newest: it keeps its room, unseen.
    const block = document.querySelector("[data-live-rival]")!;
    await vi.waitFor(() =>
      expect(block.querySelector(":scope > [data-pending]")).toHaveAttribute("aria-hidden", "true"),
    );
    expect(block.querySelector("[data-live-rival-net]")).toHaveAttribute("data-pending");
    fireEvent.click(board);
    await vi.waitFor(() => expect(block.querySelector("[data-pending]")).toBeNull());
    expect(block).toHaveTextContent(copy.live.margin);
  });

  it("keeps the duel's room while the first rival's bundle answers under the board", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-21T15:30:00Z"));
    const forwarder = fakeForwarder([
      answered(live("2026-11-21T15:29:00Z")),
      answered(live("2026-11-21T15:30:00Z", 9, 1)),
    ]);
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const read = forwarder.entryBundle.getMockImplementation()!;
    forwarder.entryBundle.mockImplementation(async (entryId: number) => {
      if (entryId !== ENTRY) await gate;
      return read(entryId);
    });
    renderLive({ forwarder });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    const block = document.querySelector("[data-live-rival]")!;
    expect(block.querySelector(":scope > [data-pending]")).not.toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    const board = await raised("goal");
    // The rival answers while the board plays: the room stays, unseen, until it has played.
    await act(async () => {
      release();
      await gate;
      // The answer is taken and drawn.
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(block.querySelector(":scope > [data-pending]")).toHaveAttribute("aria-hidden", "true");
    fireEvent.click(board);
    await vi.waitFor(() => expect(block.querySelector("[data-pending]")).toBeNull());
    expect(block).toHaveTextContent(copy.live.margin);
  });

  it("runs the board's points into Canlı puan, which pops as they land", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-21T15:30:00Z"));
    // jsdom has no Web Animations: each one here finishes at once, and the totals it moves
    // are noted.
    const popped: Element[] = [];
    Object.defineProperty(Element.prototype, "animate", {
      configurable: true,
      writable: true,
      value(this: Element) {
        if (this.matches("[data-live-total]")) popped.push(this);
        return { finished: Promise.resolve(), cancel() {} } as unknown as Animation;
      },
    });
    try {
      const forwarder = fakeForwarder([
        answered(live("2026-11-21T15:29:00Z")),
        answered(live("2026-11-21T15:30:00Z", 9, 1)),
      ]);
      renderLive({ forwarder });
      await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
      const before = Number(net());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      fireEvent.click(await raised("goal"));
      await vi.waitFor(() => expect(Number(net())).toBe(before + 6));
      // The run found LIVE's own total, in its score's head, and popped it once it landed.
      const total = document.querySelector("[data-live-total]")!;
      expect(total.closest("[data-live-head]")).not.toBeNull();
      expect(popped).toEqual([total]);
    } finally {
      delete (Element.prototype as { animate?: unknown }).animate;
    }
  });

  it("follows nothing while ?replay=1 plays, though a match is on", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-21T15:30:00Z"));
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:29:00Z", 9, 1))]);
    renderLive({
      forwarder,
      path: `/league/${LEAGUE.leagueId}/members/${ENTRY}/live?replay=1`,
    });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    // The page's first read and the replay's own read, then nothing for two minutes.
    await vi.waitFor(() => expect(forwarder.liveActivity).toHaveBeenCalledTimes(2));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2 * 60_000);
    });
    expect(forwarder.liveActivity).toHaveBeenCalledTimes(2);
  });
});

describe("the heading", () => {
  it("keeps the heading the shell focused while the squad, the read and the board arrive beside the page", async () => {
    // From 1024 px the page stands in two columns.
    screenWhere(WIDE_QUERY);
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))]);
    renderLive({ forwarder });
    // The shell focuses the page's heading on arrival, before anything below it is read.
    const heading = screen.getByRole("heading", { level: 1, name: copy.live.title });
    heading.setAttribute("tabindex", "-1");
    heading.focus();
    expect(await rows()).toHaveLength(15);
    expect(document.querySelector("[data-live-page]")).toHaveAttribute("data-wide");
    expect(screen.getByRole("heading", { level: 1 })).toBe(heading);
    expect(document.activeElement).toBe(heading);
  });
});

describe("the week and the rival", () => {
  it("shows the live week when the squad's own week is the next one", async () => {
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))]);
    // The next week's table was scored through the live week.
    renderLive({ forwarder, page: squad(TEST_WEEK + 1), members: membersScored(TEST_WEEK) });
    await rows();
    expect(
      screen.getByText(`North Stand Notes · ${copy.suggestionHistory.gameweek(TEST_WEEK)}`),
    ).toBeInTheDocument();
    expect(forwarder.entryBundle).toHaveBeenCalledWith(ENTRY, TEST_WEEK + 1, expect.anything());
    // The totals before the live week are the table's less that week's own: 132 − 74 and
    // 127 − 68, each with its live net, so the week is never counted twice.
    await screen.findByText(copy.live.totalGap);
    const net = figure(document.querySelector("[data-live-total]")?.textContent);
    const rivalNet = figure(document.querySelector("[data-live-rival-net]")?.textContent);
    expect(shownGap()).toBe(signedWhole(132 - 74 + net - (127 - 68 + rivalNet), "tr-TR"));
  });

  it("gives no total gap where the league's table is not the week's", async () => {
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))]);
    // A forwarded classic league: FPL's table moves while the week is played.
    renderLive({
      forwarder,
      forwardedLeague: { leagueId: LEAGUE.leagueId, leagueName: null, scoring: "classic" },
      members: membersScored(null),
    });
    await rows();
    const block = await vi.waitFor(() => {
      const found = document.querySelector("[data-live-rival]");
      expect(found).toHaveTextContent(copy.live.margin);
      return found!;
    });
    expect(block).not.toHaveTextContent(copy.live.totalGap);
  });

  it("sets no rival beside a team on its own", async () => {
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))]);
    renderLive({
      forwarder,
      path: `/entry/${ENTRY}/live`,
      page: squad(TEST_WEEK, 0),
      league: { ...LEAGUE, leagueId: 0 },
    });
    expect(await rows()).toHaveLength(15);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(forwarder.entryBundle).toHaveBeenCalledTimes(1);
  });

  it("sets the live week's head-to-head opponent, not the next week's, with no total gap", async () => {
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))], {
      opponent: 35249004,
    });
    renderLive({
      forwarder,
      page: squad(TEST_WEEK + 1),
      forwardedLeague: { leagueId: LEAGUE.leagueId, leagueName: null, scoring: "h2h" },
    });
    await rows();
    const select = await screen.findByRole("combobox", { name: copy.live.opponent });
    await vi.waitFor(() => expect(select).toHaveValue("35249004"));
    expect(screen.getByText(copy.live.h2h)).toBeInTheDocument();
    expect(forwarder.h2hMatches.mock.calls.map(([, gameweek]) => gameweek)).toEqual([TEST_WEEK]);
    const block = document.querySelector("[data-live-rival]")!;
    await vi.waitFor(() => expect(block).toHaveTextContent(copy.live.margin));
    expect(block).not.toHaveTextContent(copy.live.totalGap);
  });

  it.each([
    ["the week's head-to-head opponent", "h2h", 35249004, "Opponent", 1],
    ["a head-to-head league's member in a week without a pairing", "h2h", undefined, "Rival", 0],
    ["a classic league's member", "classic", undefined, "Rival", 0],
  ] as const)("names %s so in English", async (_, scoring, opponent, label, badges) => {
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))], { opponent });
    renderLive({
      forwarder,
      forwardedLeague: { leagueId: LEAGUE.leagueId, leagueName: null, scoring },
      language: "en",
    });
    await vi.waitFor(() => expect(document.querySelectorAll("[data-live-row]")).toHaveLength(15));
    const select = await screen.findByRole("combobox", { name: label });
    if (opponent !== undefined)
      await vi.waitFor(() => expect(select).toHaveValue(String(opponent)));
    expect(screen.queryAllByText(MESSAGES.en.live.h2h, { exact: true })).toHaveLength(badges);
  });

  it.each([
    ["the visitor's own", ENTRY, ["Sen", copy.live.yours, copy.live.theirs]],
    ["another member's", 35249003, ["North Stand Notes", "Half Space"]],
  ] as const)("names the sides of %s page", async (_, claimed, names) => {
    claimIn(claimed, LEAGUE.leagueId);
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))]);
    renderLive({ forwarder });
    await rows();
    const block = await vi.waitFor(() => {
      const found = document.querySelector("[data-live-rival]");
      expect(found).toHaveTextContent(copy.live.margin);
      return found!;
    });
    const differentials = document.querySelector("[data-live-differentials]")!;
    const sides = [
      ...block.querySelectorAll("p:last-of-type span"),
      ...differentials.querySelectorAll("h3"),
    ].map((node) => node.textContent ?? "");
    for (const name of names) expect(sides.join(" | ")).toContain(name);
    if (claimed !== ENTRY) expect(sides.join(" | ")).not.toContain(copy.live.yours);
  });

  it("puts the rival ?duel= names first, and a choice writes it to the address", async () => {
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))]);
    const { user } = renderLive({
      forwarder,
      path: `/league/${LEAGUE.leagueId}/members/${ENTRY}/live?duel=35249003&rival=35249004`,
    });
    await rows();
    const select = screen.getByRole("combobox", { name: copy.live.rival });
    expect(select).toHaveValue("35249003");
    await user.selectOptions(select, "35249005");
    expect(screen.getByTestId("location")).toHaveTextContent("duel=35249005");
    await vi.waitFor(() =>
      expect(forwarder.entryBundle.mock.calls.map(([entryId]) => entryId)).toContain(35249005),
    );
  });

  it("draws no state, edge or arrow, for a reserve the scorer does not count", async () => {
    // Everyone has played, so no reserve comes on; Player 4 and reserve 14 have scored.
    const input = testWeek({
      sourceTime: "2026-11-21T15:30:00Z",
      picks: testPicks().map((pick) => ({
        ...pick,
        minutes: 90,
        points: pick.id === 14 || pick.id === 4 ? 9 : 2,
      })),
    });
    const document_: WeekActivity = {
      contract_version: "week_activity_v1",
      week: input.live,
      activity: testActivity(input, { inPlay: [102], goals: { 4: 1, 14: 1 } }),
    };
    renderLive({ forwarder: fakeForwarder([answered(document_)]) });
    await rows();
    const counted = document.querySelector("[data-live-row='4']")!;
    expect(counted).toHaveAttribute("data-state", "up");
    expect(counted.querySelector(".arrow")?.childElementCount).toBe(1);
    const reserve = document.querySelector("[data-live-row='14']")!;
    expect(reserve).not.toHaveAttribute("data-counted");
    expect(reserve).not.toHaveAttribute("data-state");
    expect(reserve.querySelector(".arrow")?.childElementCount ?? 0).toBe(0);
  });

  it("keeps the duel's place, out of sight, while the first rival's bundle is read", async () => {
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))]);
    // The rival's bundle is answered after the member's board, when the test lets it go.
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const read = forwarder.entryBundle.getMockImplementation()!;
    forwarder.entryBundle.mockImplementation(async (entryId: number) => {
      if (entryId !== ENTRY) await gate;
      return read(entryId);
    });
    renderLive({ forwarder });
    await rows();
    const block = await vi.waitFor(() => {
      const found = document.querySelector("[data-live-rival]");
      expect(found).not.toBeNull();
      return found!;
    });
    const parts = () => block.querySelectorAll("p, dl, dd").length;
    const held = block.querySelector(":scope > [data-pending]");
    expect(held).toHaveAttribute("aria-hidden", "true");
    const reserved = parts();
    release();
    await vi.waitFor(() => expect(block.querySelector("[data-pending]")).toBeNull());
    expect(block).toHaveTextContent(copy.live.margin);
    // The duel took the room kept for it: nothing below it moved.
    expect(parts()).toBe(reserved);
  });

  it("keeps Farklar as the member left it and the duel's place while the next rival is read", async () => {
    screenWhere(PHONE_QUERY);
    const forwarder = fakeForwarder([answered(live("2026-11-21T15:30:00Z"))]);
    // The next rival's bundle is answered when the test lets it go.
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const read = forwarder.entryBundle.getMockImplementation()!;
    forwarder.entryBundle.mockImplementation(async (entryId: number) => {
      if (entryId === 35249005) await gate;
      return read(entryId);
    });
    const { user } = renderLive({ forwarder });
    await rows();
    const differentials = await vi.waitFor(() => {
      const found = document.querySelector<HTMLDetailsElement>("[data-live-differentials]");
      expect(found).not.toBeNull();
      return found!;
    });
    // Closed on a phone, until the member opens it.
    expect(differentials.open).toBe(false);
    await user.click(within(differentials).getByText(copy.live.differentials));
    expect(differentials.open).toBe(true);
    const block = document.querySelector("[data-live-rival]")!;
    const height = block.querySelectorAll("p, dl, [aria-hidden]").length;
    await user.selectOptions(screen.getByRole("combobox", { name: copy.live.rival }), "35249005");
    // The last duel and the last rival's points hold their places out of sight; Farklar stays
    // open, its lists unseen.
    const held = block.querySelector("[data-pending]");
    expect(held).toHaveAttribute("aria-hidden", "true");
    expect(block.querySelector("[data-live-rival-net]")).toHaveAttribute("data-pending");
    expect(block.querySelectorAll("p, dl, [aria-hidden]").length).toBe(height + 2);
    expect(document.querySelector("[data-live-differentials]")).toBe(differentials);
    expect(differentials.open).toBe(true);
    expect(differentials.querySelector("[data-pending]")).toHaveAttribute("aria-hidden", "true");
    release();
    await vi.waitFor(() => expect(document.querySelector("[data-pending]")).toBeNull());
    expect(block).toHaveTextContent(copy.live.margin);
    expect(document.querySelector("[data-live-differentials]")).toBe(differentials);
    expect(differentials.open).toBe(true);
  });
});
