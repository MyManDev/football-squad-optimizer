/**
 * When and where to act: while the week is open the top bar counts down to its deadline on
 * the page's one minute clock, and the decision ends with the way to the game, where the
 * member makes the transfers. Once the deadline has passed, both are gone.
 */
import { act, cleanup, render, renderHook, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { withLeague } from "../../../testSupport/league";
import type { FixturesPayload } from "../../fixtures/types";
import { passedDeadline, useMinuteClock } from "../advice/deadline";
import type { EntryAdvice } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";
import type { LeagueMemberViewProps } from "./memberPageTypes";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const ENTRY = 35249001;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;
const DEADLINE = "2026-10-23T17:30:00Z";
const CALENDAR: FixturesPayload = {
  season: SQUAD.payload.season,
  source_snapshot_id: "calendar-test",
  captured_at_utc: "2026-10-20T00:00:00Z",
  current_gameweek: SQUAD.payload.gameweek,
  unscheduled_count: 0,
  gameweeks: [{ gameweek: SQUAD.payload.gameweek, deadline_utc: DEADLINE, fixtures: [] }],
};
const before = (minutes: number) => Date.parse(DEADLINE) - minutes * 60_000;

/** The example member's one-week plan; it holds the team and keeps the held captain. */
function plan(patch: (payload: EntryAdvice) => Partial<EntryAdvice> = () => ({})) {
  const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
  return { ...base, payload: { ...base.payload, ...patch(base.payload) } };
}
const { moves, expected_gain_vs_hold } = mockEntryAdviceEnvelope(ENTRY, "agresif", 1).payload;
const WITH_MOVE = plan(() => ({ moves, expected_gain_vs_hold }));

function page(language: Language, props: Partial<LeagueMemberViewProps> = {}) {
  return (
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}`]}>
        {withLeague(
          <LeagueMemberView
            index={mockEntryAdviceIndex(ENTRY).payload}
            squad={SQUAD}
            advice={WITH_MOVE}
            fixtures={CALENDAR}
            {...props}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>
  );
}

/** As LeagueMemberPage wires it: one clock, read for the deadline check and the countdown. */
function Clocked({ language }: { language: Language }) {
  const now = useMinuteClock();
  return page(language, { now, deadlinePassed: passedDeadline(DEADLINE, now) });
}

const countdown = () => screen.queryByTestId("deadline-countdown");
const fplLink = (language: Language) =>
  screen.queryByRole("link", { name: MESSAGES[language].leagueMembers.applyOnFpl });

describe("the top bar's countdown", () => {
  it.each([
    [2 * 1440 + 14 * 60 + 5, "2 gün 14 sa kaldı", "2 d 14 h left", false],
    [3 * 60 + 12.5, "3 sa 12 dk kaldı", "3 h 12 min left", false],
    [60, "1 sa kaldı", "1 h left", false],
    [12, "12 dk kaldı", "12 min left", true],
    [0.5, "1 dk'dan az kaldı", "under 1 min left", true],
  ] as const)("reads %s minutes before the deadline", (minutes, tr, en, urgent) => {
    for (const [language, text] of [
      ["tr", tr],
      ["en", en],
    ] as const) {
      render(page(language, { now: before(minutes) }));
      const tag = countdown()!;
      expect(tag).toHaveTextContent(text);
      expect(tag.tagName).toBe("TIME");
      expect(tag).toHaveAttribute("datetime", DEADLINE);
      expect(tag.hasAttribute("data-urgent")).toBe(urgent);
      // Nothing re-announces it as it changes: it is read where the reader reaches it.
      expect(tag.closest("[aria-live]")).toBeNull();
      cleanup();
    }
  });

  it("moves once a minute on the page's clock and is gone once the deadline passes", () => {
    vi.useFakeTimers({ now: before(61) });
    render(<Clocked language="tr" />);
    expect(countdown()).toHaveTextContent("1 sa 1 dk kaldı");
    act(() => vi.advanceTimersByTime(59_999));
    expect(countdown()).toHaveTextContent("1 sa 1 dk kaldı");
    act(() => vi.advanceTimersByTime(1));
    expect(countdown()).toHaveTextContent("1 sa kaldı");
    act(() => vi.advanceTimersByTime(60_000));
    expect(countdown()).toHaveTextContent("59 dk kaldı");
    expect(countdown()).toHaveAttribute("data-urgent");
    expect(fplLink("tr")).not.toBeNull();
    act(() => vi.advanceTimersByTime(59 * 60_000));
    expect(countdown()).toBeNull();
    expect(screen.getByText(MESSAGES.tr.leagueMembers.deadlinePassedLabel)).toBeInTheDocument();
    expect(fplLink("tr")).toBeNull();
  });

  it("is left out without the page's clock", () => {
    render(page("en"));
    expect(countdown()).toBeNull();
  });
});

describe("the page's minute clock", () => {
  it("reads the clock it is given once a minute, on one timer it stops when the page goes", () => {
    vi.useFakeTimers();
    let time = 1_000;
    const clock = () => time;
    const { result, unmount } = renderHook(() => useMinuteClock(clock));
    expect(result.current).toBe(1_000);
    expect(vi.getTimerCount()).toBe(1);
    time = 61_000;
    act(() => vi.advanceTimersByTime(60_000));
    expect(result.current).toBe(61_000);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("the way to apply the decision on FPL", () => {
  it.each(["tr", "en"] as const)(
    "opens the game's transfers page in a new tab while the week is open (%s)",
    (language) => {
      const copy = MESSAGES[language].leagueMembers;
      render(page(language, { now: before(90) }));
      const decision = screen.getByRole("region", { name: copy.decisionTitle });
      const link = within(decision).getByRole("link", { name: copy.applyOnFpl });
      expect(link).toHaveAttribute("href", "https://fantasy.premierleague.com/transfers");
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
      expect(link).toHaveAccessibleDescription(copy.applyTransfersHint);
    },
  );

  it.each(["tr", "en"] as const)(
    "is gone, with the countdown, after the deadline (%s)",
    (language) => {
      render(page(language, { now: before(-1), deadlinePassed: DEADLINE }));
      const copy = MESSAGES[language].leagueMembers;
      expect(screen.getByText(copy.deadlinePassedLabel)).toBeInTheDocument();
      expect(countdown()).toBeNull();
      expect(fplLink(language)).toBeNull();
      cleanup();
      // Nor is it offered while the calendar does not say the week is open.
      render(page(language, { fixtures: null }));
      expect(fplLink(language)).toBeNull();
    },
  );

  it("sends a week without a transfer to the team page when the plan moves the armband", () => {
    const copy = MESSAGES.en.leagueMembers;
    const armband = plan((payload) => ({
      captain: payload.vice_captain,
      vice_captain: payload.captain,
    }));
    render(page("en", { advice: armband }));
    const link = fplLink("en")!;
    expect(link).toHaveAttribute("href", "https://fantasy.premierleague.com/my-team");
    expect(link).toHaveAccessibleDescription(copy.applyCaptainHint);
    cleanup();
    // Holding the team with the captain who already wears the armband leaves nothing to apply.
    render(page("en", { advice: plan() }));
    expect(fplLink("en")).toBeNull();
  });
});
