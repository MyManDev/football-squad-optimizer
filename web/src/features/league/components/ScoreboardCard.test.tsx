import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import type { LeagueViewEnvelope, Scoreboard } from "../types";
import { ScoreboardCard, ScoreboardSection } from "./ScoreboardCard";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// The web guard's regex, verbatim: no percent sign, no probability in any spelling.
const FORBIDDEN = /%|probabilit|olasılık|\bP\(/i;

/** The shape the producer wrote from the 2026-09-07 GW4 capture, with the numbers rounded. */
const scoreboard: LeagueViewEnvelope<Scoreboard> = {
  contract_version: "provisional_league_ui_v1",
  generated_at_utc: "2026-09-07T13:20:00Z",
  source_kind: "live",
  payload: {
    season: "2026-27",
    league_id: 352490,
    source_snapshot_id: "fpl-live-20260907T131414Z-db9314d00961",
    captured_at_utc: "2026-09-07T13:14:14Z",
    cohort_snapshot_id: "fpl-top100-20260907T131112Z-1b1419176245",
    registered_members: 15,
    histories_held: 15,
    gameweeks: [
      {
        gameweek: 1,
        deadline_utc: "2026-08-21T17:30:00Z",
        finished: true,
        data_checked: true,
        average_entry_score: 50,
        highest_score: 131,
        ours: { net: 26, xi: 26, hits: 0, projected: 56.1, mode: "live" },
        top100: null,
        members: [],
        members_mean_net: 54.3,
        members_counted: 15,
      },
      {
        gameweek: 2,
        deadline_utc: "2026-08-28T17:30:00Z",
        finished: true,
        data_checked: true,
        average_entry_score: 81,
        highest_score: 161,
        ours: { net: null, xi: null, hits: 4, projected: 60.2, mode: "replay" },
        top100: null,
        members: [],
        members_mean_net: 86.3,
        members_counted: 15,
      },
      {
        gameweek: 3,
        deadline_utc: "2026-09-04T17:30:00Z",
        finished: true,
        data_checked: true,
        average_entry_score: 51,
        highest_score: 119,
        ours: null,
        top100: { gameweek: 3, mean_event_total: 68.79, cohort_size: 100, final: true },
        members: [],
        members_mean_net: 58.7,
        members_counted: 15,
      },
      {
        gameweek: 4,
        deadline_utc: "2026-09-12T12:30:00Z",
        finished: false,
        data_checked: false,
        average_entry_score: null,
        highest_score: null,
        ours: null,
        top100: null,
        members: [],
        members_mean_net: null,
        members_counted: 0,
      },
    ],
    cumulative: {
      through_gameweek: 3,
      gameweeks: [1, 2, 3],
      ours_net: 26,
      ours_gameweeks: [1],
      members_mean_total_points: 199.2,
      members_counted: 15,
      average_entry_score: 182,
    },
  },
};

function renderCard(envelope: LeagueViewEnvelope<Scoreboard>, language: Language = "en") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <ScoreboardCard envelope={envelope} />
    </LanguageProvider>,
  );
}

function renderSection(language: Language = "en") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <LanguageProvider initialLanguage={language}>
      <QueryClientProvider client={client}>
        <ScoreboardSection />
      </QueryClientProvider>
    </LanguageProvider>,
  );
}

describe("scoreboard card", () => {
  it.each(["tr", "en"] as const)("shows one row per finished gameweek in %s", (language) => {
    const copy = MESSAGES[language].leagueScoreboard;
    const { container } = renderCard(scoreboard, language);

    expect(screen.getByRole("heading", { name: copy.title })).toBeInTheDocument();
    // Three finished weeks in the body, one cumulative row in the foot, one header row.
    expect(screen.getAllByRole("row")).toHaveLength(5);
    expect(screen.getByRole("columnheader", { name: copy.ours })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: copy.cumulative(3) })).toBeInTheDocument();
    expect(screen.getByText(copy.paperLedger)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(FORBIDDEN);
  });

  it("labels our row with the mode it was decided in and withholds an unsettled net", () => {
    renderCard(scoreboard);
    const rows = screen.getAllByRole("row");
    const gw1 = rows[1].querySelectorAll("td");
    expect(gw1[0].textContent).toContain("26");
    expect(gw1[0].textContent).toContain("live");
    const gw2 = rows[2].querySelectorAll("td");
    expect(gw2[0].textContent).toContain("—");
    expect(gw2[0].textContent).toContain("replay");
    expect(gw2[0].textContent).toContain(MESSAGES.en.leagueScoreboard.notSettled);
    // No ledger entry at all: a dash, no badge.
    const gw3 = rows[3].querySelectorAll("td");
    expect(gw3[0].textContent).toBe("—");
  });

  it("shows the members' mean net, the Top-100 mean for its own week, the average and the highest", () => {
    renderCard(scoreboard);
    const rows = screen.getAllByRole("row");
    const gw3 = rows[3].querySelectorAll("td");
    expect(gw3[1].textContent).toContain("58.7");
    expect(gw3[1].textContent).toContain("15 members");
    expect(gw3[2].textContent).toContain("68.8");
    expect(gw3[2].textContent).not.toContain("not final");
    expect(gw3[3].textContent).toBe("51");
    expect(gw3[4].textContent).toBe("119");
    // The Top-100 capture describes one week; the others carry a dash, not a copy.
    expect(rows[1].querySelectorAll("td")[2].textContent).toBe("—");
  });

  it("marks a Top-100 mean read before the week was checked as not final", () => {
    const unchecked = structuredClone(scoreboard);
    unchecked.payload.gameweeks[2].top100!.final = false;
    renderCard(unchecked);
    expect(screen.getByText("not final")).toBeInTheDocument();
  });

  it("names the weeks the cumulative figures cover", () => {
    renderCard(scoreboard);
    const foot = screen.getByRole("rowheader", { name: /cumulative through GW3/ }).closest("tr")!;
    const cells = foot.querySelectorAll("td");
    expect(cells[0].textContent).toContain("26");
    expect(cells[0].textContent).toContain("GW 1 only");
    expect(cells[1].textContent).toContain("199.2");
    expect(cells[1].textContent).toContain("mean total of 15");
    expect(cells[3].textContent).toBe("182");
  });

  it("says when no gameweek has finished instead of drawing an empty table", () => {
    const empty = structuredClone(scoreboard);
    empty.payload.gameweeks = empty.payload.gameweeks.map((week) => ({ ...week, finished: false }));
    empty.payload.cumulative = {
      through_gameweek: null,
      gameweeks: [],
      ours_net: null,
      ours_gameweeks: [],
      members_mean_total_points: null,
      members_counted: 0,
      average_entry_score: null,
    };
    renderCard(empty);
    expect(screen.getByText(MESSAGES.en.leagueScoreboard.noGameweek)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("scoreboard section", () => {
  it.each(["tr", "en"] as const)(
    "reads as not published yet when the file is missing, in %s",
    async (language) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
      renderSection(language);
      expect(
        await screen.findByText(MESSAGES[language].leagueScoreboard.notPublished),
      ).toBeInTheDocument();
    },
  );

  it("treats the app shell served for an unknown path as not published", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<!doctype html><html></html>", {
          status: 200,
          headers: { "Content-Type": "text/html" },
        }),
      ),
    );
    renderSection();
    expect(await screen.findByText(MESSAGES.en.leagueScoreboard.notPublished)).toBeInTheDocument();
  });

  it("reports a server failure as unreadable rather than as unpublished", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 500 })));
    renderSection();
    expect(await screen.findByText(MESSAGES.en.leagueScoreboard.notAvailable)).toBeInTheDocument();
  });

  it("renders the published document", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(scoreboard), { status: 200 })),
    );
    renderSection();
    expect(
      await screen.findByRole("rowheader", { name: /cumulative through GW3/ }),
    ).toBeInTheDocument();
  });
});
