import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { SUPPORTED_LEAGUE_ID } from "../data";
import { readChosenLeague, writeChosenLeague } from "../identity/useChosenLeague";
import { LeagueGate } from "./LeagueGate";

const published = { ...mockLeagueMembersEnvelope, source_kind: "live" };

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  localStorage.clear();
  writeChosenLeague(null);
});

function open(language: Language, address = "/league/members/35249001") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[address]}>
        <Routes>
          <Route
            path="/league/members/:entryId"
            element={
              <LeagueGate>
                <h1>Member page</h1>
              </LeagueGate>
            }
          />
          <Route path="/league/members" element={<h1>Members list</h1>} />
        </Routes>
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe.each(["tr", "en"] as const)("league gate in %s", (language) => {
  const copy = MESSAGES[language].leagueEntry;

  it("shows the entry form at the page's own address until the league number is given", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(published)));
    vi.stubGlobal("fetch", fetcher);
    open(language);
    expect(screen.getByRole("heading", { name: copy.title })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Member page" })).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.label), String(SUPPORTED_LEAGUE_ID));
    await user.click(screen.getByRole("button", { name: copy.submit }));

    // The page the visitor asked for opens in place; no detour through the members list.
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Members list" })).toBeNull();
    expect(readChosenLeague()).toBe(SUPPORTED_LEAGUE_ID);
    expect(localStorage.getItem("squadopt.league")).toBe(String(SUPPORTED_LEAGUE_ID));
  });

  it("opens the page directly when the league is remembered", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    writeChosenLeague(SUPPORTED_LEAGUE_ID);
    open(language);
    expect(screen.getByRole("heading", { name: "Member page" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: copy.title })).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("asks again when the remembered league is not the published one", () => {
    writeChosenLeague(123456);
    open(language);
    expect(screen.getByRole("heading", { name: copy.title })).toBeInTheDocument();
    expect(screen.getByLabelText(copy.label)).toHaveValue("123456");
    expect(screen.queryByRole("heading", { name: "Member page" })).toBeNull();
  });

  it("keeps an unsupported number out of the gate", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    open(language);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.label), "123");
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(screen.getByRole("status")).toHaveTextContent(copy.unsupported);
    expect(screen.queryByRole("heading", { name: "Member page" })).toBeNull();
    expect(readChosenLeague()).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
