import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { textByNode } from "../../../testSupport/textByNode";
import type { LeagueViewEnvelope, Scoreboard } from "../types";
import { ScoreboardCard, ScoreboardSection } from "./ScoreboardCard";
import { withLeague } from "../../../testSupport/league";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** The document the producer wrote from the 2026-09-07 GW4 capture, as typed, numbers rounded. */
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
    cohort_picks_snapshot_id: "fpl-elite-picks-20260907T131133Z-6517b37b5afe",
    gameweeks: [
      {
        gameweek: 1,
        deadline_utc: "2026-08-21T17:30:00Z",
        finished: true,
        data_checked: true,
        average_entry_score: 50,
        highest_score: 131,
        ours: {
          net: 26,
          xi: 26,
          hits: 0,
          projected: 56.1,
          scoring_basis: "named_eleven_no_autosubs",
          vice_captain_named: false,
        },
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
        ours: {
          net: null,
          xi: null,
          hits: 4,
          projected: 60.2,
          scoring_basis: "named_eleven_no_autosubs",
          vice_captain_named: false,
        },
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
        top100: {
          gameweek: 3,
          basis: "net",
          mean_score: 68.75,
          cohort_size: 100,
          final: true,
        },
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
      members_mean_total_points: 199.2,
      members_counted: 15,
      average_entry_score: 182,
    },
  },
};

/** The pipeline's own English words, as whole words. */
const PIPELINE_WORDS = /\b(capture|ledger|live|replay|bench|snapshot|GW)\b/i;

/** The same capture with its most qualified figure: a gross, unfinal Top-100 in an unchecked week. */
function qualified(): LeagueViewEnvelope<Scoreboard> {
  const value = structuredClone(scoreboard);
  const top100 = value.payload.gameweeks[2].top100!;
  top100.basis = "gross";
  top100.final = false;
  value.payload.gameweeks[2].data_checked = false;
  return value;
}

/** Each cell's text, the row's own header first. */
function cellsOf(row: Element): (string | null)[] {
  return [...row.querySelectorAll("th, td")].map((cell) => cell.textContent);
}

function renderCard(envelope: LeagueViewEnvelope<Scoreboard>, language: Language = "en") {
  return render(
    <LanguageProvider initialLanguage={language}>
      {withLeague(<ScoreboardCard envelope={envelope} />)}
    </LanguageProvider>,
  );
}

function renderSection(language: Language = "en") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <LanguageProvider initialLanguage={language}>
      <QueryClientProvider client={client}>{withLeague(<ScoreboardSection />)}</QueryClientProvider>
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
    expect(screen.getByRole("rowheader", { name: copy.cumulative(3) })).toBeInTheDocument();
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
  });

  it.each(["en", "tr"] as const)(
    "heads the table with the week and its four figures in %s",
    (language) => {
      const copy = MESSAGES[language].leagueScoreboard;
      renderCard(scoreboard, language);
      const table = screen.getByRole("table", { name: copy.caption });
      expect(
        within(table)
          .getAllByRole("columnheader")
          .map((header) => header.textContent),
      ).toEqual([copy.gameweek, copy.members, copy.top100, copy.average, copy.highest]);
    },
  );

  it("shows the members' mean net, the Top-100 mean for its own week, the average and the highest", () => {
    renderCard(scoreboard);
    const rows = screen.getAllByRole("row");
    expect(cellsOf(rows[3])).toEqual(["3", "58.7", "68.8", "51", "119"]);
    // The Top-100 capture describes one week; the others carry a dash, not a copy.
    expect(cellsOf(rows[1])).toEqual(["1", "54.3", "—", "50", "131"]);
  });

  it("shows a qualified figure on its own", () => {
    renderCard(qualified());
    expect(cellsOf(screen.getAllByRole("row")[3])).toEqual(["3", "58.7", "68.8", "51", "119"]);
  });

  it("totals the members and the FPL average in the cumulative row", () => {
    renderCard(scoreboard);
    const foot = screen.getByRole("rowheader", { name: /cumulative through GW3/ }).closest("tr")!;
    expect(cellsOf(foot).slice(1)).toEqual(["199.2", "—", "182", "—"]);
  });

  it("speaks Turkish to a Turkish reader, the hidden caption included", () => {
    const { container } = renderCard(qualified(), "tr");
    // Read node by node: textContent glues a header cell to the next element's text
    // and a whole-word check cannot see it there.
    expect(textByNode(container)).not.toMatch(PIPELINE_WORDS);
  });

  it("leaves the pipeline's words out of the English card too", () => {
    const { container } = renderCard(qualified(), "en");
    // GW is the game's own word for a week, and the English table heads its column with it.
    expect(textByNode(container).replace(/\bGW\d*\b/g, "")).not.toMatch(PIPELINE_WORDS);
    expect(container.textContent).not.toContain(scoreboard.payload.source_snapshot_id.slice(0, 24));
  });

  it("names the table and words its empty states in the reader's terms", () => {
    const { tr, en } = MESSAGES;
    expect(tr.leagueScoreboard.caption).toBe(
      "Biten her oyun haftası için: lig üyelerinin ortalama neti, Top-100 ortalaması, FPL ortalaması, en yüksek puan",
    );
    expect(en.leagueScoreboard.caption).toBe(
      "Per finished gameweek: the league members' mean net, the Top-100 mean, the FPL average, the highest score",
    );
    expect(tr.leagueScoreboard.noGameweek).toBe("Henüz biten oyun haftası yok.");
    expect(en.leagueScoreboard.noGameweek).toBe("No gameweek has finished yet.");
    expect(tr.leagueScoreboard.notPublished).toBe("Skor tablosu henüz yayımlanmadı.");
    expect(en.leagueScoreboard.notPublished).toBe("The scoreboard is not published yet.");
  });

  it.each(["en", "tr"] as const)(
    "says when no gameweek has finished instead of drawing an empty table, in %s",
    (language) => {
      const empty = structuredClone(scoreboard);
      empty.payload.gameweeks = empty.payload.gameweeks.map((week) => ({
        ...week,
        finished: false,
      }));
      empty.payload.cumulative = {
        through_gameweek: null,
        gameweeks: [],
        members_mean_total_points: null,
        members_counted: 0,
        average_entry_score: null,
      };
      const { container } = renderCard(empty, language);
      expect(screen.getByText(MESSAGES[language].leagueScoreboard.noGameweek)).toBeInTheDocument();
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      // The empty card, its line included, is Turkish to a Turkish reader.
      if (language === "tr") expect(textByNode(container)).not.toMatch(PIPELINE_WORDS);
    },
  );
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

  it("renders the published document, the only one it reads", async () => {
    const reads = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(scoreboard), { status: 200 }));
    vi.stubGlobal("fetch", reads);
    renderSection();
    expect(
      await screen.findByRole("rowheader", { name: /cumulative through GW3/ }),
    ).toBeInTheDocument();
    expect(reads).toHaveBeenCalledTimes(1);
  });
});
