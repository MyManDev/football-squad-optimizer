/**
 * /league/<id> (where an old /league bookmark lands) is its title over the weekly table, read
 * from the league's scoreboard alone.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { stubTree, withLeague } from "../../../testSupport/league";
import { raceScoreboard, raceWeek } from "../../../testSupport/raceScoreboard";
import type { LeagueTree } from "../data";
import { LeagueDataMissing } from "../dataErrors";
import { LeaguePage } from "./LeaguePage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const season = "2026-27";

const notPublished = () =>
  vi.fn<LeagueTree["scoreboard"]>().mockRejectedValue(new LeagueDataMissing("scoreboard.json"));

const published = () =>
  vi.fn<LeagueTree["scoreboard"]>().mockResolvedValue({
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-10-02T10:00:00Z",
    source_kind: "live",
    payload: raceScoreboard([raceWeek(1, { 101: 50 })]),
  });

function renderLeague(language: Language, scoreboard: LeagueTree["scoreboard"] = notPublished()) {
  stubTree({ scoreboard });
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queries}>
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={["/league/352490"]}>
          {withLeague(<LeaguePage />)}
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

describe.each(["tr", "en"] as const)("the league page in %s", (language) => {
  const copy = MESSAGES[language];

  it("holds its title over the weekly table, with no caveat", async () => {
    const { container } = renderLeague(language);
    expect(await screen.findByText(copy.leagueScoreboard.notPublished)).toBeInTheDocument();
    expect(screen.getAllByRole("heading").map((heading) => heading.textContent)).toEqual([
      copy.league.title,
      copy.leagueScoreboard.title,
    ]);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(AS_A_CHANCE);
    expect(text).not.toMatch(AS_A_CAVEAT);
  });

  it("draws one table, under the scoreboard's own season, and no link leaves it", async () => {
    const { container } = renderLeague(language, published());
    expect(await screen.findAllByRole("table")).toHaveLength(1);
    expect(screen.getByRole("table", { name: copy.leagueScoreboard.caption })).toBeInTheDocument();
    expect(container).toHaveTextContent(`${copy.league.season} ${season}`);
    expect(container.querySelector("a")).toBeNull();
  });

  it("names no season the scoreboard did not give, and still holds its title", async () => {
    const { container } = renderLeague(language);
    await screen.findByText(copy.leagueScoreboard.notPublished);
    expect(container).not.toHaveTextContent(season);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(copy.league.title);
  });

  it("draws the table from the scoreboard alone, asking nothing else of the network", async () => {
    const asked = vi.fn<typeof fetch>(() => Promise.reject(new Error("Refused.")));
    vi.stubGlobal("fetch", asked);
    renderLeague(language, published());
    expect(
      await screen.findByRole("table", { name: copy.leagueScoreboard.caption }),
    ).toBeInTheDocument();
    expect(asked).not.toHaveBeenCalled();
  });
});
