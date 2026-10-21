import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { FixturesPayload } from "../../fixtures/types";
import { MemberSquad } from "../pages/MemberSquad";
import { squadOnPitch } from "../pages/squadOnPitch";
import type { CoachAbsence } from "../advice/coachAbsences";
import type { EntryAdvice } from "../types";

const ENTRY = 35249001;
const held = mockEntrySquadEnvelopes[ENTRY]!.payload;
const original = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1).payload;
const player = original.starting_xi![0]!;

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = true;
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = false;
    },
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function calendar(): FixturesPayload {
  return {
    season: original.season,
    source_snapshot_id: original.source_snapshot_id!,
    captured_at_utc: "2026-10-21T10:00:00Z",
    current_gameweek: original.gameweek,
    unscheduled_count: 0,
    gameweeks: [
      {
        gameweek: original.gameweek,
        deadline_utc: "2026-10-23T17:30:00Z",
        fixtures: [
          {
            fixture_id: 40,
            kickoff_utc: "2026-10-24T14:00:00Z",
            finished: false,
            home_score: null,
            away_score: null,
            home: { team_id: 1, name: player.team, short_name: "HOM" },
            away: { team_id: 2, name: "Visitors", short_name: "VIS" },
          },
        ],
      },
    ],
  };
}
function plan(): EntryAdvice {
  return {
    ...original,
    moves: [
      {
        move_id: "in",
        player_in: player,
        player_out: null,
        expected_points_delta: 2,
        reason_code: "points_gain",
      },
    ],
    role_forecast: {
      version: "football_role_forecast_v1",
      model_version: "football_composite_v1",
      calibration: "not_independently_verified",
      scope: "current_gameweek_fixtures",
      rows: [
        {
          player_id: player.player_id,
          name: player.name,
          fixture_id: 40,
          gameweek: original.gameweek,
          kickoff: "2026-10-24T14:00:00Z",
          expected_minutes: 67.5,
          status: "fitted_known_start_labels",
          captured_eligibility_multiplier: 1,
          news_applied: false,
        },
      ],
    },
  };
}
function view(
  advice = plan(),
  fixtures: FixturesPayload | null = calendar(),
  language: "tr" | "en" = "tr",
  news = new Map<number, CoachAbsence>(),
) {
  return (
    <LanguageProvider initialLanguage={language}>
      <MemberSquad
        onPitch={squadOnPitch(advice, held)}
        plan={advice}
        held={held}
        codes={new Map()}
        fixtures={fixtures}
        news={news}
        list={null}
      />
    </LanguageProvider>
  );
}
function open() {
  const trigger = screen.getByRole("button", { name: `${player.name}: Oyuncu ayrıntıları` });
  trigger.focus();
  fireEvent.click(trigger);
  return trigger;
}

it("opens the chosen player's published points, fixture, minutes and transfer reason, then restores focus", () => {
  render(view());
  const trigger = open();
  expect(screen.getByRole("dialog", { name: player.name })).toBeVisible();
  expect(screen.getByText("Beklenen dakika: 67,5")).toBeVisible();
  expect(screen.getByText("Visitors")).toBeVisible();
  expect(screen.getByText("Bu haftanın beklenen puanına göre önerildi.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Kapat" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(trigger).toHaveFocus();
});

it.each(["missing", "stale", "other-season"])(
  "does not invent a fixture or minutes from a %s calendar",
  (kind) => {
    const fixtures = calendar();
    if (kind === "stale") fixtures.source_snapshot_id = "other-capture";
    if (kind === "other-season") fixtures.season = "2025-26";
    render(view(plan(), kind === "missing" ? null : fixtures));
    open();
    expect(screen.queryByText("Bu haftanın maçları")).toBeNull();
    expect(screen.queryByText(/Beklenen dakika/)).toBeNull();
  },
);

it.each([
  "absent",
  "other-player",
  "other-week",
  "other-fixture",
  "duplicate",
  "invalid",
  "unavailable",
])("does not show %s minutes as this player's estimate", (kind) => {
  const advice = plan();
  const row = advice.role_forecast!.rows[0]!;
  if (kind === "absent") delete advice.role_forecast;
  if (kind === "other-player") row.player_id += 100000;
  if (kind === "other-week") row.gameweek += 1;
  if (kind === "other-fixture") row.fixture_id += 1;
  if (kind === "duplicate") advice.role_forecast!.rows.push({ ...row });
  if (kind === "invalid") row.expected_minutes = NaN;
  if (kind === "unavailable") row.status = "unavailable_no_known_start_labels";
  render(view(advice));
  open();
  expect(screen.queryByText(/Beklenen dakika/)).toBeNull();
  expect(screen.getByText("Visitors")).toBeVisible();
});

it("keeps a published fitted zero distinct from an unavailable minutes estimate", () => {
  const advice = plan();
  advice.role_forecast!.rows[0]!.expected_minutes = 0;
  render(view(advice));
  open();
  expect(screen.getByText("Beklenen dakika: 0,0")).toBeVisible();
});

it("closes a selected player when the capture or member changes", () => {
  const { rerender } = render(view());
  open();
  rerender(view({ ...plan(), source_snapshot_id: "next-capture" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("provides a named button for a bench player's details too", () => {
  render(view());
  const bench = original.bench![0]!;
  fireEvent.click(screen.getByRole("button", { name: `${bench.name}: Oyuncu ayrıntıları` }));
  expect(screen.getByRole("dialog", { name: bench.name })).toBeVisible();
  expect(screen.queryByText("Bu transfer neden?")).toBeNull();
});

it("keeps the news source independent from the player button and shows its exact quote in the dialog", () => {
  const news = new Map([
    [
      player.player_id,
      {
        playerId: player.player_id,
        words: "He will not play on Saturday.",
        sourceUrl: "https://www.liverpoolfc.com/news/team-news",
        publishedAt: "2026-10-21T09:00:00Z",
      },
    ],
  ]);
  render(view(plan(), calendar(), "tr", news));
  const mark = screen.getByRole("link", { name: /Hoca: bu maçta yok/ });
  expect(mark.closest("button")).toBeNull();
  expect(mark).toHaveAttribute("href", news.get(player.player_id)!.sourceUrl);
  open();
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("He will not play on Saturday.")).toBeVisible();
  expect(within(dialog).getByRole("link", { name: "Haberi oku" })).toHaveAttribute(
    "href",
    news.get(player.player_id)!.sourceUrl,
  );
});
